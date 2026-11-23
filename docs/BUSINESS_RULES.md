# Business rules and policy

Everything here is implemented in `backend/app/services/` and enforced by code, never by a prompt.
**The LLM extracts text into fields; it never decides, never does arithmetic that matters, and never sees PO or vendor data.**

## 1. Decision model

| Decision | Meaning | Produced when |
|---|---|---|
| `APPROVED` | Safe to pay | Every mandatory control passes and nothing is flagged |
| `NEEDS_REVIEW` | A human must decide | Any rule is `FAIL` or `REVIEW`, or a mandatory control could not be evaluated |
| `REJECTED` | Blocked | A **hard-block** rule failed: confirmed duplicate (R08) or blocked vendor (R02), or a reviewer rejected it |
| `PROCESSING_ERROR` | The pipeline failed | Corrupt / encrypted / non-PDF file, OCR failure, AI provider outage after retries, DB error. **Not** a business decision |

Rule statuses: `PASS`, `FAIL` (clear evidence of a violated control), `REVIEW` (uncertain / missing data), `NOT_APPLICABLE`
(an upstream rule already blocks it, e.g. no PO to compare against).
Mandatory controls for approval: R01 R02 R03 R04 R05 R06 R08 R09 R10 R14 R15 R16.

## 2. The rules

| ID | Name | Pass condition | Fail / review outcome |
|---|---|---|---|
| R01 | Required fields | Invoice number, date, vendor, total and PO reference present | `REVIEW`; missing invoice number explains that duplicate checking is impossible; missing PO lists *suggested* POs |
| R02 | Approved vendor | Vendor verified and `APPROVED` | Blocked → `FAIL` + hard block; inactive → `FAIL`; unrecognised / ambiguous → `REVIEW` |
| R03 | PO existence | Referenced PO exists | Not found → `FAIL`; no reference → `REVIEW` |
| R04 | Vendor–PO consistency | PO belongs to the invoicing vendor | `FAIL` (policy: review, never auto-approve; likely typo, misdirected or fraudulent) |
| R05 | Currency | Invoice currency equals PO currency | `FAIL` (no conversion policy is configured) |
| R06 | Invoice arithmetic | `subtotal − discount + shipping + tax = grand total` ± 0.05 | `FAIL` |
| R07 | Line arithmetic | `qty × unit price = line total`; lines sum to subtotal | `FAIL` |
| R08 | Duplicates | No identical file, no same-vendor + same-number invoice | Confirmed → `FAIL` + hard block; suspicious → `REVIEW`; no invoice number → `REVIEW` |
| R09 | PO amount | Invoice total ≤ PO authorized total | `FAIL` |
| R10 | Partial invoicing | Invoice total ≤ PO authorized − sum(previously **approved** invoices) | `FAIL` (shows remaining before / after) |
| R11 | Amount tolerance | `|invoice − PO-priced amount| / PO-priced amount × 100 ≤ 1 %` (or fixed tolerance) | `FAIL` |
| R12 | Tax reconciliation | Stated tax = recomputed tax (line rates, else PO rate) | `FAIL` / `REVIEW` (discount makes base ambiguous) |
| R13 | Dates | Plausible: not future, not stale (> 365 d), not before the PO date, due ≥ invoice | `REVIEW` |
| R14 | PO status | PO not closed and has balance | `FAIL` |
| R15 | Extraction reliability | Key values appear verbatim in the document text; OCR confidence ≥ 85 %; no embedded AI instructions | `REVIEW` |
| R16 | Line matching | Every invoice line maps to a PO line within remaining PO quantity | Unmapped / bundled / ambiguous → `REVIEW`; quantity over PO → `FAIL` |

### Tolerance (R11) in detail
* **Applies to** the price/total variance only. Default `TOLERANCE_PCT=1.0`; optional fixed amount `TOLERANCE_ABS`.
* The expected amount is computed from the invoice's own lines at **PO prices and PO tax** (`Σ qty × PO unit price × (1 + PO tax)`), so partial billing is not mistaken for a variance.
* **Tolerance can never be used to exceed the PO.** R09/R10 are strict comparisons, evaluated independently
  (see sample 08: price 0.9 % over is *within tolerance*, but the total exceeds the remaining balance, so it is held).
* Rounding: arithmetic checks allow ±0.05 (`ROUNDING_TOLERANCE`).

### Vendor matching order
1. verified tax ID → 2. exact legal name → 3. approved alias → 4. normalised name (suffixes like Pvt/Ltd/LLP removed)
→ 5. fuzzy similarity ≥ 0.82 is only ever a **suggestion** (`AMBIGUOUS`, never auto-matched).
Inconsistent identity (tax ID of vendor A with the name of vendor B; right name, wrong tax ID) is `AMBIGUOUS`.

### Duplicates
* Identical **file** (SHA-256) or same **vendor + normalised invoice number** (case / punctuation insensitive): confirmed → `REJECTED`; the original is cited.
* Same vendor + same total + (same date **or** number similarity ≥ 0.8): suspicious → `REVIEW`.
* The same number from a *different* vendor is **not** a duplicate.
* Duplicates are never allocated against the PO (R09/R10/R11/R14/R16 become not-applicable).

### Partial invoicing & PO balance
* Remaining balance is **derived**, not trusted: `authorized_total − Σ APPROVED invoices on the PO`. `purchase_orders.remaining_balance` is only a cache that is recomputed (`reconcile_po`) on every allocation; the PO page shows whether the cache is reconciled.
* Per-line quantity is tracked the same way (`quantity − Σ approved quantity on that PO line`).
* Only `APPROVED` invoices consume balance. Reviews, rejections and errors never do.

## 3. Concurrency & idempotency
* The final stage re-evaluates **all** shared-state rules (vendor, PO, duplicates, balance) and writes the decision inside one critical section: a process lock **plus** `BEGIN IMMEDIATE` (SQLite) / `SELECT … FOR UPDATE` on the PO row (PostgreSQL).
  Tests: six simultaneous invoices racing for a PO with room for two → exactly two approved; three simultaneous invoices with the same vendor+number → one approved, two rejected as duplicates.
* Re-processing an `APPROVED` invoice is refused (returns the existing run), so allocation can never be applied twice.

## 4. Human review policy
* Reviewers can: correct extracted fields (whitelisted), re-run validation, **approve**, **reject**, or **request clarification**; each needs a written justification (≥ 10 chars) and is recorded in the audit trail with reviewer, previous value, new value and time.
* **Manual approval cannot bypass hard controls.** Non-bypassable: R01 (missing identity data), R02 (blocked/inactive/unknown vendor), R03, R04, R05, R09, R10, R14 and confirmed duplicates. Fix those by correcting the data (and re-validating), or upstream (PO amendment, vendor master).
  Bypassable with justification (judgement calls): R06/R07/R12 arithmetic, R11 price variance, R13 dates, R15 reliability, R16 line mapping, *suspected* duplicates. Overridden rules are listed on the decision and in the audit event.
* Corrected data is **never auto-approved**: after a correction the best automatic outcome is `NEEDS_REVIEW`, and the reviewer must approve explicitly (the approval re-runs every check under the PO lock).
* Approved invoices are locked from re-processing and from corrections.

## 5. Security posture (prototype)
* Uploads: PDF signature + size checks, random server-side file names, sanitised display names, page limit.
* Invoice text is **untrusted**: the extraction prompt forbids following instructions inside it; embedded "approve this invoice" style text is detected, flagged (R15) and ignored; the decision logic is code, so it cannot be steered.
* Extracted values must be found verbatim in the document (R15), which catches hallucinated invoice numbers / totals.
* API errors are generic; stack traces and keys never reach the UI. Keys come from environment variables only.
* The demo has **no authentication** (a single demo reviewer identity is recorded). This is a demonstration mechanism, not production security.
* This system **makes decisions only; it never executes payments.**
