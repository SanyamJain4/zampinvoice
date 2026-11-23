# 5-minute demo script

**Before recording:** start the API (`cd backend && uvicorn app.main:app --port 8000`), open `http://127.0.0.1:8000`, go to **Settings → Reset demo data**.
Have `sample_data/invoices/` open in a file window as a fallback (drag-and-drop works exactly like *Add*). Browser at ~1440 px wide so the live view sits beside the queue.
If you have an API key, add it to `.env` first so the header says `Extraction: anthropic` — otherwise say plainly that this run uses the offline parser and why that is safe (rules, not AI, decide).

| Time | Do | Say |
|---|---|---|
| **0:00–0:30** | Overview page (empty state). Point at the sidebar and the header chips. | "An AP team gets hundreds of PDF invoices. Today someone opens each, finds the PO, checks the maths, hunts for duplicates. InvoiceIQ automates that: AI reads the document, deterministic rules decide, and a person only sees what is genuinely uncertain. It makes decisions only — it never pays." |
| **0:30–1:45** | **Process Invoice** → *Add* "Valid invoice (happy path)" → **Start processing**. Click through stages 3, 6, 8, 9 in the timeline; show the green banner with *remaining before/after*. | "Every stage is real backend work, persisted as it happens — start, finish, duration, data. Stage 3 extracts fields with evidence. Vendor verified against the vendor master, PO found, lines matched to PO lines, 16 rules run. Approved, with the reason and the PO balance effect." |
| **1:45–2:30** | *Add* "Duplicate of an already-approved invoice" (or add the same valid sample again) → Start. | "Same vendor and invoice number as one already approved: confirmed duplicate, blocked, original cited — and it never touches the PO balance. Different vendors with the same number are not flagged." |
| **2:30–3:15** | *Add* "Amount mismatch". Open full result → **Decision & checks**: expand R11. Then open the **Review panel**: show *Approve* locked. | "Billed ₹64,900 against a ₹59,000 PO: |64,900 − 59,000| ÷ 59,000 = 10 % — above the 1 % tolerance, and above what the PO authorizes. It goes to a human, and the hard controls can't be clicked away." |
| **3:15–4:00** | *Add* sample 4 (35,000) → Start; then sample 4b (30,000). **Purchase Orders** → PO-500 drawer. | "A PO can be billed in parts. 40,000 already approved, so 60,000 left; this 35,000 is approved and leaves 25,000. The next 30,000 invoice would overdraw it — held, nothing allocated. Balances are derived from approved invoices, and the last stage re-checks under a lock, so two simultaneous invoices can't both win." |
| **4:00–4:40** | **Overview** (KPIs/charts), **Audit Trail**, open **Processing log** on one invoice. Optional: **Review Queue** → missing-number invoice → correct → approve. | "Dashboard is computed from persisted runs. Every action — extraction, matches, decision, manual correction, approval — is in an append-only audit trail with who, when, before/after and why." |
| **4:40–5:00** | Back to the timeline or Settings. | "AI is used where documents are messy — extraction. Money decisions are plain Python with Decimal arithmetic, so they're explainable and testable. Uncertainty — missing data, ambiguity, scans with doubt — goes to a person; pipeline failures are 'processing errors', never silent rejections. Result: the clean 80 % flows straight through; humans spend time only on exceptions." |

## Edge cases to have ready for the live interview (each ~30 s)
1. **Scanned** – `06a` (OCR badge, confidence) then `06b` (OCR + mismatch).
2. **Missing invoice number** – `05` → Review panel: approve is locked; **Correct data** → re-validate → "corrected data needs explicit approval" → approve (audit shows before/after).
3. **Tolerance vs balance** – `08`: price is within 1 % **but** total exceeds remaining balance → still held.
4. **Prompt injection** – `13`: footer tries to command the AI; warning in Stage 2, R15 flags it, decision unchanged.
5. **Bundled lines** – `10`: line matching shows the bundle equals three PO lines but isn't itemised.
6. **Failure ≠ rejection** – upload any text file renamed `.pdf` (rejected at upload), or a corrupt PDF → *Processing error* banner with "not a business rejection".
7. **Concurrency** – drop `04` and `04b` together (batch): server serialises the decisions.
   (For the scripted flow run `04` **before** `04b`; in a batch the result depends on which wins the lock — that is the point of the lock.)

## Resilience notes
* The app does not need the internet in offline mode; with an LLM key, a transient API error is retried (bounded) and a hard failure shows as *Processing error* with a one-click **Retry processing** — the demo can continue with the next sample.
* **Settings → Reset demo data** returns to a clean state in one click. The 17 sample PDFs are bundled in the UI (*Bundled samples*), so no file picking is needed.
* If SSE is blocked by a proxy, the timeline switches to polling automatically (a "polling" chip appears on the queue item).
