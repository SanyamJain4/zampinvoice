"""Deterministic financial rule engine (R01-R16). No LLM is involved in any rule or amount.

Status semantics
  PASS            control satisfied
  FAIL            a control failed with clear evidence
  REVIEW          the system cannot be certain (missing / ambiguous data)
  NOT_APPLICABLE  rule cannot be evaluated because an upstream rule already blocks it
A FAIL/REVIEW never auto-approves. Only rules flagged `hard_block` (confirmed duplicate, blocked vendor)
produce a REJECTED decision; everything else routes to a human (NEEDS_REVIEW).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable

from app.core.config import Settings
from app.schemas.extraction import ExtractedInvoice
from app.services.common import dec, money, norm_company, q2, within_tolerance
from app.services.duplicate_detector import DuplicateResult
from app.services.po_matcher import LineMatchResult, POMatch
from app.services.vendor_matcher import VendorMatch

ZERO = Decimal("0")


@dataclass
class RuleResult:
    rule_id: str
    rule_name: str
    status: str
    severity: str
    expected: str
    observed: str
    explanation: str
    hard_block: bool = False
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id, "rule_name": self.rule_name, "status": self.status, "severity": self.severity,
            "expected": self.expected, "observed": self.observed, "explanation": self.explanation,
            "hard_block": self.hard_block, "details": self.details,
        }


@dataclass
class Ctx:
    ex: ExtractedInvoice
    settings: Settings
    vendor: VendorMatch
    po: POMatch
    lines: LineMatchResult
    dup: DuplicateResult
    balance: dict | None  # po_balance() of the matched PO (excluding this invoice)
    raw_text: str = ""
    ocr_confidence: float | None = None
    extraction_method: str = ""
    injection_hits: list[str] = field(default_factory=list)
    corrected_fields: set[str] = field(default_factory=set)
    today: date = field(default_factory=date.today)

    @property
    def cur(self) -> str | None:
        return self.ex.currency

    @property
    def currency_ok(self) -> bool:
        return bool(self.po.po and self.ex.currency and self.ex.currency == self.po.po.currency)

    @property
    def is_dup(self) -> bool:
        return self.dup.status == "CONFIRMED"


def _r(rule_id, name, status, severity, expected, observed, explanation, hard=False, **details) -> RuleResult:
    return RuleResult(rule_id, name, status, severity, expected, observed, explanation, hard, details)


def _po(ctx: Ctx):
    return ctx.po.po


# ---------------------------------------------------------------------------- R01
def r01(ctx: Ctx) -> RuleResult:
    ex = ctx.ex
    missing = []
    checks = [("invoice_number", ex.invoice_number), ("invoice_date", ex.invoice_date), ("vendor_name", ex.vendor_name),
              ("grand_total", ex.grand_total), ("po_number", ex.po_number)]
    for k, v in checks:
        if v in (None, ""):
            missing.append(k)
    if not missing:
        return _r("R01", "Required Fields Check", "PASS", "HIGH", "Invoice number, date, vendor, total and PO reference present",
                  "All required fields present", "All required fields were found on the invoice.")
    nice = [m.replace("_", " ") for m in missing]
    expl = f"Missing: {', '.join(nice)}."
    if "invoice_number" in missing:
        expl += " Without an invoice number the invoice cannot be reliably identified and duplicate verification cannot be completed."
    if "po_number" in missing:
        expl += " Without a PO reference the invoice cannot be matched to a purchase order automatically."
        if ctx.po.candidates:
            expl += " Suggested POs (unconfirmed): " + ", ".join(c["po_number"] for c in ctx.po.candidates) + "."
    return _r("R01", "Required Fields Check", "REVIEW", "HIGH", "Invoice number, date, vendor, total and PO reference present",
              f"Missing: {', '.join(nice)}", expl, missing=missing)


# ---------------------------------------------------------------------------- R02
def r02(ctx: Ctx) -> RuleResult:
    v = ctx.vendor
    exp = "Vendor verified and approved"
    if v.status == "VERIFIED_APPROVED":
        return _r("R02", "Approved Vendor Check", "PASS", "CRITICAL", exp, f"{v.vendor.legal_name} ({v.vendor.vendor_id}) approved",
                  f"{v.message} Vendor is approved.", vendor=v.to_dict())
    if v.status == "BLOCKED":
        return _r("R02", "Approved Vendor Check", "FAIL", "CRITICAL", exp, f"{v.vendor.legal_name} is BLOCKED",
                  f"Vendor {v.vendor.legal_name} is blocked under company policy. No invoice from this vendor may be paid.", True, vendor=v.to_dict())
    if v.status == "VERIFIED_INACTIVE":
        return _r("R02", "Approved Vendor Check", "FAIL", "CRITICAL", exp, f"{v.vendor.legal_name} is INACTIVE",
                  f"Vendor {v.vendor.legal_name} is inactive. Procurement must re-activate the vendor before payment.", vendor=v.to_dict())
    if v.status == "AMBIGUOUS":
        return _r("R02", "Approved Vendor Check", "REVIEW", "CRITICAL", exp, "Ambiguous vendor match", v.message, vendor=v.to_dict())
    return _r("R02", "Approved Vendor Check", "REVIEW", "CRITICAL", exp, "Vendor not recognised", v.message, vendor=v.to_dict())


# ---------------------------------------------------------------------------- R03
def r03(ctx: Ctx) -> RuleResult:
    exp = "Referenced PO exists"
    if ctx.po.status == "MATCHED":
        return _r("R03", "Purchase Order Existence", "PASS", "HIGH", exp, ctx.po.po.po_number, f"PO {ctx.po.po.po_number} exists in the procurement system.")
    if ctx.po.status == "NOT_FOUND":
        return _r("R03", "Purchase Order Existence", "FAIL", "HIGH", exp, f"'{ctx.ex.po_number}' not found", ctx.po.message, candidates=ctx.po.candidates)
    return _r("R03", "Purchase Order Existence", "REVIEW", "HIGH", exp, "No PO reference", ctx.po.message, candidates=ctx.po.candidates)


# ---------------------------------------------------------------------------- R04
def r04(ctx: Ctx) -> RuleResult:
    exp = "PO belongs to the invoicing vendor"
    if not _po(ctx):
        return _r("R04", "Vendor–PO Consistency", "NOT_APPLICABLE", "CRITICAL", exp, "No PO matched", "No PO to compare the vendor against.")
    if not ctx.vendor.verified:
        return _r("R04", "Vendor–PO Consistency", "NOT_APPLICABLE", "CRITICAL", exp, "Vendor not verified", "Vendor identity is unresolved (see R02).")
    po = _po(ctx)
    if ctx.po.vendor_consistent:
        return _r("R04", "Vendor–PO Consistency", "PASS", "CRITICAL", exp, f"{po.po_number} → {po.vendor.legal_name}",
                  f"PO {po.po_number} was issued to {po.vendor.legal_name}, the same vendor as the invoice.")
    return _r("R04", "Vendor–PO Consistency", "FAIL", "CRITICAL", exp,
              f"Invoice vendor: {ctx.vendor.vendor.legal_name}; PO vendor: {po.vendor.legal_name}",
              f"The invoice is from {ctx.vendor.vendor.legal_name} but PO {po.po_number} belongs to {po.vendor.legal_name}. "
              "Possible wrong PO reference or misdirected / fraudulent invoice. Policy: send to manual review, never auto-approve.")


# ---------------------------------------------------------------------------- R05
def r05(ctx: Ctx) -> RuleResult:
    exp = "Invoice currency equals PO currency"
    if not _po(ctx):
        return _r("R05", "Currency Validation", "NOT_APPLICABLE", "HIGH", exp, "No PO matched", "No PO currency to compare.")
    if not ctx.ex.currency:
        return _r("R05", "Currency Validation", "REVIEW", "HIGH", exp, "Invoice currency not found", "The invoice does not state a currency.")
    if ctx.ex.currency == _po(ctx).currency:
        return _r("R05", "Currency Validation", "PASS", "HIGH", exp, ctx.ex.currency, f"Both invoice and PO are in {ctx.ex.currency}.")
    return _r("R05", "Currency Validation", "FAIL", "HIGH", exp, f"Invoice {ctx.ex.currency} vs PO {_po(ctx).currency}",
              f"The invoice is in {ctx.ex.currency} but the PO is in {_po(ctx).currency}. No currency-conversion policy is configured, "
              "so amounts cannot be compared automatically.")


# ---------------------------------------------------------------------------- R06
def _doc_subtotal(ex: ExtractedInvoice) -> tuple[Decimal | None, str]:
    if ex.subtotal is not None:
        return ex.subtotal, "stated subtotal"
    totals = [l.line_total for l in ex.line_items]
    if totals and all(t is not None for t in totals):
        return sum(totals, ZERO), "sum of line totals"
    return None, ""


def r06(ctx: Ctx) -> RuleResult:
    ex, tol = ctx.ex, ctx.settings.rounding_tolerance
    exp = "Subtotal − Discount + Shipping + Tax = Grand total (±rounding)"
    if ex.grand_total is None:
        return _r("R06", "Invoice Arithmetic", "REVIEW", "HIGH", exp, "Grand total missing", "The grand total is missing, so the arithmetic cannot be verified.")
    sub, src = _doc_subtotal(ex)
    if sub is None:
        return _r("R06", "Invoice Arithmetic", "REVIEW", "HIGH", exp, "Subtotal not available", "Neither a subtotal nor complete line totals are available to verify the grand total.")
    disc, ship, tax = ex.discount or ZERO, ex.shipping or ZERO, ex.tax_amount or ZERO
    calc = sub - disc + ship + tax
    diff = abs(calc - ex.grand_total)
    formula = f"{money(sub)} − {money(disc)} + {money(ship)} + {money(tax)} = {money(calc)}"
    if diff <= tol:
        return _r("R06", "Invoice Arithmetic", "PASS", "HIGH", exp, f"{formula} (stated {money(ex.grand_total)})",
                  f"Totals reconcile ({src}); difference {money(diff)} is within the {tol} rounding allowance.", difference=str(q2(diff)))
    note = " No tax amount was found on the invoice." if ex.tax_amount is None else ""
    return _r("R06", "Invoice Arithmetic", "FAIL", "HIGH", exp, f"{formula} but stated total is {money(ex.grand_total)}",
              f"The invoice does not add up: computed {money(calc)} vs stated {money(ex.grand_total)} (difference {money(diff)}).{note}",
              difference=str(q2(diff)))


# ---------------------------------------------------------------------------- R07
def r07(ctx: Ctx) -> RuleResult:
    ex, tol = ctx.ex, ctx.settings.rounding_tolerance
    exp = "Quantity × unit price = line total; lines sum to subtotal"
    if not ex.line_items:
        return _r("R07", "Line-Item Arithmetic", "NOT_APPLICABLE", "MEDIUM", exp, "No line items", "No line items were extracted (see R16).")
    bad, verifiable = [], 0
    for i, l in enumerate(ex.line_items, 1):
        if l.quantity is not None and l.unit_price is not None and l.line_total is not None:
            verifiable += 1
            if abs(l.quantity * l.unit_price - l.line_total) > tol:
                bad.append(f"Line {i}: {l.quantity} × {l.unit_price} = {money(l.quantity * l.unit_price)} but line total is {money(l.line_total)}")
    sum_note = ""
    totals = [l.line_total for l in ex.line_items]
    if ex.subtotal is not None and all(t is not None for t in totals):
        s = sum(totals, ZERO)
        if abs(s - ex.subtotal) > tol * max(1, len(totals)):
            bad.append(f"Line totals sum to {money(s)} but the subtotal is {money(ex.subtotal)}")
        else:
            sum_note = f" Line totals sum to the subtotal ({money(s)})."
    if bad:
        return _r("R07", "Line-Item Arithmetic", "FAIL", "MEDIUM", exp, "; ".join(bad), "Line arithmetic errors: " + "; ".join(bad) + ".", errors=bad)
    if verifiable == 0 and not sum_note:
        return _r("R07", "Line-Item Arithmetic", "NOT_APPLICABLE", "MEDIUM", exp, "Lines lack quantity/unit price", "Line items do not state quantity and unit price, so line arithmetic cannot be verified.")
    return _r("R07", "Line-Item Arithmetic", "PASS", "MEDIUM", exp, f"{verifiable}/{len(ex.line_items)} lines verified",
              f"Quantity × unit price equals the line total on {verifiable} line(s).{sum_note}")


# ---------------------------------------------------------------------------- R08
def r08(ctx: Ctx) -> RuleResult:
    d = ctx.dup
    exp = "No earlier invoice with the same vendor + number, and no identical file"
    if d.status == "CONFIRMED":
        o = d.original
        return _r("R08", "Duplicate Detection", "FAIL", "CRITICAL", exp, d.message,
                  f"Confirmed duplicate: {d.message} Duplicates never consume PO balance. Original: invoice #{o.id}.", True,
                  kind=d.kind, matches=d.matches)
    if d.status == "SUSPECTED":
        return _r("R08", "Duplicate Detection", "REVIEW", "MEDIUM", exp, d.message,
                  f"Possible duplicate: {d.message} A reviewer must confirm that this is a different invoice.", kind=d.kind, matches=d.matches)
    if d.status == "NOT_CHECKABLE":
        return _r("R08", "Duplicate Detection", "REVIEW", "HIGH", exp, "Duplicate check incomplete", d.message)
    return _r("R08", "Duplicate Detection", "PASS", "CRITICAL", exp, "No duplicate found", d.message)


# ---------------------------------------------------------------------------- R09 / R10 / R11
def _money_rule_na(ctx: Ctx, rid: str, name: str, sev: str, exp: str) -> RuleResult | None:
    if ctx.is_dup:
        return _r(rid, name, "NOT_APPLICABLE", sev, exp, "Duplicate", "Skipped: a confirmed duplicate never consumes PO balance.")
    if not _po(ctx):
        return _r(rid, name, "NOT_APPLICABLE", sev, exp, "No PO matched", "No PO to compare against.")
    if not ctx.currency_ok:
        return _r(rid, name, "NOT_APPLICABLE", sev, exp, "Currency not comparable", "Skipped: invoice and PO currencies differ or are unknown (see R05).")
    if ctx.ex.grand_total is None:
        return _r(rid, name, "NOT_APPLICABLE", sev, exp, "No invoice total", "The invoice total is missing (see R01).")
    return None


def r09(ctx: Ctx) -> RuleResult:
    exp = "Invoice total ≤ PO authorized total"
    na = _money_rule_na(ctx, "R09", "PO Amount Validation", "HIGH", exp)
    if na:
        return na
    po, cur, total = _po(ctx), ctx.cur, ctx.ex.grand_total
    if total <= po.authorized_total:
        return _r("R09", "PO Amount Validation", "PASS", "HIGH", exp, f"{money(total, cur)} ≤ {money(po.authorized_total, cur)}",
                  f"The invoice total does not exceed the authorized PO value of {money(po.authorized_total, cur)}.")
    over = total - po.authorized_total
    return _r("R09", "PO Amount Validation", "FAIL", "HIGH", exp, f"{money(total, cur)} > {money(po.authorized_total, cur)}",
              f"The invoice total exceeds the entire PO authorization by {money(over, cur)}. Tolerance can never be used to exceed the authorized amount.",
              excess=str(q2(over)))


def r10(ctx: Ctx) -> RuleResult:
    exp = "Invoice total ≤ remaining PO balance (after previously approved invoices)"
    na = _money_rule_na(ctx, "R10", "Partial Invoice Validation", "HIGH", exp)
    if na:
        return na
    po, cur, total, bal = _po(ctx), ctx.cur, ctx.ex.grand_total, ctx.balance
    before = bal["remaining_before"]
    after = before - total
    detail = dict(authorized=str(po.authorized_total), previously_approved=str(bal["approved_total"]),
                  remaining_before=str(before), invoice=str(total), remaining_after=str(q2(after)),
                  approved_invoices=bal["approved_invoices"])
    line = (f"Authorized {money(po.authorized_total, cur)} − previously approved {money(bal['approved_total'], cur)} "
            f"= remaining {money(before, cur)}; this invoice {money(total, cur)} → remaining after {money(after, cur)}")
    if after >= 0:
        return _r("R10", "Partial Invoice Validation", "PASS", "HIGH", exp, line,
                  f"Sufficient balance. Remaining before: {money(before, cur)}; after approval: {money(after, cur)}.", **detail)
    return _r("R10", "Partial Invoice Validation", "FAIL", "HIGH", exp, line,
              f"Insufficient PO balance: only {money(before, cur)} remains but the invoice is {money(total, cur)} "
              f"(over by {money(-after, cur)}). Not auto-approved and no balance is allocated.", **detail)


def r11(ctx: Ctx) -> RuleResult:
    exp = f"Invoice total within {ctx.settings.tolerance_pct}% (or fixed {ctx.settings.tolerance_abs}) of the PO-priced amount"
    na = _money_rule_na(ctx, "R11", "Amount Tolerance", "MEDIUM", exp)
    if na:
        return na
    cur, total, lm = ctx.cur, ctx.ex.grand_total, ctx.lines
    if not lm.all_mapped or lm.expected_total is None:
        return _r("R11", "Amount Tolerance", "NOT_APPLICABLE", "MEDIUM", exp, "Expected amount unavailable",
                  "The PO-priced amount cannot be computed because not every invoice line maps to a PO line (see R16).")
    ok, pct, diff = within_tolerance(total, lm.expected_total, ctx.settings.tolerance_pct, ctx.settings.tolerance_abs)
    formula = f"|{money(total)} − {money(lm.expected_total)}| ÷ {money(lm.expected_total)} × 100 = {pct}%"
    detail = dict(expected_total=str(lm.expected_total), invoice_total=str(total), variance_pct=str(pct), variance_abs=str(diff),
                  tolerance_pct=str(ctx.settings.tolerance_pct), tolerance_abs=str(ctx.settings.tolerance_abs))
    if ok:
        note = "exact match" if diff == 0 else f"within the {ctx.settings.tolerance_pct}% tolerance"
        return _r("R11", "Amount Tolerance", "PASS", "MEDIUM", exp, formula,
                  f"Invoice total {money(total, cur)} vs PO-priced amount {money(lm.expected_total, cur)}: {note}.", **detail)
    direction = "above" if total > lm.expected_total else "below"
    return _r("R11", "Amount Tolerance", "FAIL", "MEDIUM", exp, formula,
              f"Invoice total {money(total, cur)} is {pct}% ({money(diff, cur)}) {direction} the PO-priced amount "
              f"{money(lm.expected_total, cur)}; tolerance is {ctx.settings.tolerance_pct}%.", **detail)


# ---------------------------------------------------------------------------- R12
def r12(ctx: Ctx) -> RuleResult:
    ex, tol = ctx.ex, ctx.settings.rounding_tolerance
    exp = "Tax amount equals tax rate × taxable value"
    if ex.tax_amount is None:
        if ex.line_items and any(l.tax_rate for l in ex.line_items):
            return _r("R12", "Tax Reconciliation", "REVIEW", "MEDIUM", exp, "Tax amount not found", "Line tax rates are present but no tax amount was found to reconcile.")
        return _r("R12", "Tax Reconciliation", "NOT_APPLICABLE", "MEDIUM", exp, "No tax stated", "The invoice states no tax; nothing to reconcile.")
    if (ex.discount or ZERO) > 0:
        return _r("R12", "Tax Reconciliation", "REVIEW", "MEDIUM", exp, "Document-level discount present",
                  "A document-level discount makes the taxable base ambiguous, so tax cannot be re-computed automatically.")
    rated = [l for l in ex.line_items if l.tax_rate is not None and l.line_total is not None]
    if rated and len(rated) == len(ex.line_items):
        expected = sum((l.line_total * l.tax_rate / 100 for l in rated), ZERO)
        basis = "line tax rates"
    else:
        sub, _ = _doc_subtotal(ex)
        rates = {pl.tax_rate for pl in _po(ctx).lines} if _po(ctx) else set()
        if sub is None or len(rates) != 1:
            return _r("R12", "Tax Reconciliation", "NOT_APPLICABLE", "MEDIUM", exp, "Insufficient data", "Not enough information (rates or subtotal) to re-compute tax.")
        rate = next(iter(rates))
        expected, basis = sub * rate / 100, f"PO tax rate {rate}%"
    allowed = tol * max(1, len(ex.line_items)) + tol
    diff = abs(expected - ex.tax_amount)
    if diff <= allowed:
        return _r("R12", "Tax Reconciliation", "PASS", "MEDIUM", exp, f"Computed {money(expected)} vs stated {money(ex.tax_amount)}",
                  f"Tax reconciles using {basis} (difference {money(diff)}).")
    return _r("R12", "Tax Reconciliation", "FAIL", "MEDIUM", exp, f"Computed {money(expected)} vs stated {money(ex.tax_amount)}",
              f"Stated tax {money(ex.tax_amount)} differs from the recomputed {money(expected)} ({basis}) by {money(diff)}.")


# ---------------------------------------------------------------------------- R13
def r13(ctx: Ctx) -> RuleResult:
    ex, s = ctx.ex, ctx.settings
    exp = "Valid, plausible invoice date"
    if ex.invoice_date is None:
        return _r("R13", "Date Validation", "REVIEW", "MEDIUM", exp, "Invoice date missing", "No readable invoice date was found.")
    issues = []
    if ex.invoice_date > ctx.today + timedelta(days=s.future_date_grace_days):
        issues.append(f"invoice date {ex.invoice_date} is in the future")
    if ex.invoice_date < ctx.today - timedelta(days=s.max_invoice_age_days):
        issues.append(f"invoice date {ex.invoice_date} is more than {s.max_invoice_age_days} days old (stale)")
    po = _po(ctx)
    if po and ex.invoice_date < po.issue_date:
        issues.append(f"invoice date {ex.invoice_date} is before the PO was issued ({po.issue_date})")
    if ex.due_date and ex.due_date < ex.invoice_date:
        issues.append(f"due date {ex.due_date} is before the invoice date")
    if issues:
        return _r("R13", "Date Validation", "REVIEW", "MEDIUM", exp, "; ".join(issues), "Suspicious date(s): " + "; ".join(issues) + ".")
    return _r("R13", "Date Validation", "PASS", "LOW", exp, str(ex.invoice_date), f"Invoice date {ex.invoice_date} is plausible.")


# ---------------------------------------------------------------------------- R14
def r14(ctx: Ctx) -> RuleResult:
    exp = "PO is open and has remaining balance"
    po = _po(ctx)
    if not po:
        return _r("R14", "PO Status", "NOT_APPLICABLE", "HIGH", exp, "No PO matched", "No PO status to check.")
    if ctx.is_dup:
        return _r("R14", "PO Status", "NOT_APPLICABLE", "HIGH", exp, "Duplicate", "Skipped for a confirmed duplicate.")
    if po.status == "CLOSED":
        return _r("R14", "PO Status", "FAIL", "HIGH", exp, "PO is CLOSED", f"PO {po.po_number} is closed; new invoices cannot be auto-approved against it.")
    if ctx.balance and ctx.balance["remaining_before"] <= 0:
        return _r("R14", "PO Status", "FAIL", "HIGH", exp, "PO fully invoiced", f"PO {po.po_number} is fully invoiced; there is no remaining balance.")
    state = "partially invoiced" if ctx.balance and ctx.balance["approved_total"] > 0 else "open"
    return _r("R14", "PO Status", "PASS", "HIGH", exp, state.upper(), f"PO {po.po_number} is {state}.")


# ---------------------------------------------------------------------------- R15
def _norm_alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _amount_in_text(text: str, value: Decimal) -> bool:
    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", text):
        try:
            if Decimal(m.group(0).replace(",", "")) == value:
                return True
        except Exception:
            continue
    return False


def r15(ctx: Ctx) -> RuleResult:
    ex = ctx.ex
    exp = "Extracted values are grounded in the document; no OCR doubt; no embedded instructions"
    problems, sev = [], "MEDIUM"
    if ctx.injection_hits:
        problems.append("The document contains text that looks like instructions to an AI system (ignored by the system): "
                        + " | ".join(ctx.injection_hits[:2]))
        sev = "HIGH"
    if ctx.ocr_confidence is not None and ctx.ocr_confidence < ctx.settings.ocr_low_confidence:
        problems.append(f"OCR confidence is low ({ctx.ocr_confidence:.0%})")
    bad_parse = [w for w in ex.warnings if "Could not read" in w or "not a recognised" in w]
    problems.extend(bad_parse)
    ungrounded = []
    if ctx.raw_text:
        flat = _norm_alnum(ctx.raw_text)
        for fname in ("invoice_number", "po_number", "vendor_name"):
            val = getattr(ex, fname)
            if val and fname not in ctx.corrected_fields and _norm_alnum(val) not in flat:
                ungrounded.append(fname.replace("_", " "))
        if ex.grand_total is not None and "grand_total" not in ctx.corrected_fields and not _amount_in_text(ctx.raw_text, ex.grand_total):
            ungrounded.append("grand total")
    if ungrounded:
        problems.append("Value(s) not found verbatim in the document text: " + ", ".join(ungrounded) + " (possible extraction error)")
    if problems:
        return _r("R15", "Extraction Reliability", "REVIEW", sev, exp, "; ".join(problems), "Extraction reliability concerns: " + "; ".join(problems) + ".",
                  ungrounded=ungrounded, injection=ctx.injection_hits)
    note = f"extracted by {ctx.extraction_method}" if ctx.extraction_method else "extraction verified"
    if ctx.corrected_fields:
        note += f"; {len(ctx.corrected_fields)} field(s) corrected by a reviewer"
    return _r("R15", "Extraction Reliability", "PASS", "MEDIUM", exp, "Key fields found verbatim in the document", f"Key extracted values are grounded in the source text ({note}).")


# ---------------------------------------------------------------------------- R16
def r16(ctx: Ctx) -> RuleResult:
    exp = "Every invoice line maps to a PO line within the remaining PO quantity"
    if not _po(ctx):
        return _r("R16", "Line-Item Matching", "NOT_APPLICABLE", "MEDIUM", exp, "No PO matched", "No PO lines to compare against.")
    if ctx.is_dup:
        return _r("R16", "Line-Item Matching", "NOT_APPLICABLE", "MEDIUM", exp, "Duplicate", "Skipped for a confirmed duplicate.")
    if not ctx.ex.line_items:
        return _r("R16", "Line-Item Matching", "REVIEW", "MEDIUM", exp, "No line items extracted", "No line items were extracted, so billed items cannot be verified against the PO.")
    lm = ctx.lines
    unmapped = [l for l in lm.lines if l["status"] not in ("MATCHED", "PRICE_MISMATCH", "QTY_EXCEEDED")]
    over = [l for l in lm.lines if l["status"] == "QTY_EXCEEDED"]
    if over:
        return _r("R16", "Line-Item Matching", "FAIL", "HIGH", exp, "; ".join(f"Line {l['index']}: {l['note']}" for l in over),
                  "Billed quantity exceeds what remains on the PO: " + "; ".join(l["note"] for l in over), lines=lm.lines)
    if unmapped:
        why = "; ".join(f"Line {l['index']} ({l['status'].lower()}): {l['note']}" for l in unmapped)
        return _r("R16", "Line-Item Matching", "REVIEW", "MEDIUM", exp, why,
                  f"{len(unmapped)} line(s) cannot be confidently mapped to PO lines: {why}", lines=lm.lines)
    return _r("R16", "Line-Item Matching", "PASS", "MEDIUM", exp, f"{len(lm.lines)} line(s) mapped",
              f"All {len(lm.lines)} invoice line(s) map to PO lines within the remaining PO quantity.", lines=lm.lines)


RULES: dict[str, Callable[[Ctx], RuleResult]] = {
    "R01": r01, "R02": r02, "R03": r03, "R04": r04, "R05": r05, "R06": r06, "R07": r07, "R08": r08,
    "R09": r09, "R10": r10, "R11": r11, "R12": r12, "R13": r13, "R14": r14, "R15": r15, "R16": r16,
}

STAGE_RULES = {
    "invoice_validation": ["R01", "R06", "R07", "R12", "R13", "R15"],
    "vendor_verification": ["R02"],
    "po_matching": ["R03", "R04", "R05", "R14"],
    "duplicate_detection": ["R08"],
    "financial_reconciliation": ["R16", "R09", "R10", "R11"],
}


def run_rules(ctx: Ctx, ids: list[str] | None = None) -> list[RuleResult]:
    return [RULES[i](ctx) for i in (ids or list(RULES))]
