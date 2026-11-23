"""PO lookup, balance accounting and line-item matching (all deterministic, Decimal based)."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.models import Invoice, InvoiceLine, POLine, PurchaseOrder
from app.schemas.extraction import ExtractedInvoice
from app.services.common import dec, norm_po, q2, text_similarity, within_tolerance
from app.services.vendor_matcher import VendorMatch

ZERO = Decimal("0")


# ------------------------------------------------------------------ PO lookup
@dataclass
class POMatch:
    status: str  # MATCHED | NOT_FOUND | NO_REFERENCE
    po: PurchaseOrder | None = None
    message: str = ""
    candidates: list[dict] = field(default_factory=list)
    vendor_consistent: bool | None = None  # None = vendor unverified / not comparable

    def to_dict(self) -> dict:
        return {
            "status": self.status, "message": self.message, "candidates": self.candidates,
            "vendor_consistent": self.vendor_consistent,
            "po": None if not self.po else po_brief(self.po),
        }


def po_brief(po: PurchaseOrder) -> dict:
    return {
        "id": po.id, "po_number": po.po_number, "vendor": po.vendor.legal_name if po.vendor else None,
        "currency": po.currency, "authorized_total": str(po.authorized_total), "status": po.status,
        "issue_date": po.issue_date.isoformat(),
    }


def match_po(db: Session, ex: ExtractedInvoice, vendor: VendorMatch, exclude_invoice_id: int | None = None) -> POMatch:
    ref = norm_po(ex.po_number)
    if not ref:
        cands = suggest_pos(db, ex, vendor, exclude_invoice_id)
        msg = "The invoice has no purchase-order reference."
        if cands:
            msg += " Possible POs: " + ", ".join(c["po_number"] for c in cands) + " (suggestions only; a human must confirm)."
        return POMatch("NO_REFERENCE", message=msg, candidates=cands)
    for po in db.scalars(select(PurchaseOrder)):
        if norm_po(po.po_number) == ref:
            consistent = None
            if vendor.verified:
                consistent = po.vendor_id == vendor.vendor.id
            return POMatch("MATCHED", po, f"PO {po.po_number} found.", vendor_consistent=consistent)
    cands = suggest_pos(db, ex, vendor, exclude_invoice_id)
    return POMatch("NOT_FOUND", message=f"PO '{ex.po_number}' does not exist in the procurement system.", candidates=cands)


def suggest_pos(db: Session, ex: ExtractedInvoice, vendor: VendorMatch, exclude_invoice_id: int | None) -> list[dict]:
    """Candidate POs for a missing/unknown reference. Suggestions only; never auto-selected."""
    if not vendor.verified:
        return []
    out = []
    for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.vendor_id == vendor.vendor.id)):
        if po.status == "CLOSED":
            continue
        bal = po_balance(db, po, exclude_invoice_id)
        if bal["remaining_before"] <= 0:
            continue
        score = 0.0
        if ex.grand_total is not None and ex.grand_total <= bal["remaining_before"]:
            score += 0.3
            if ex.grand_total == po.authorized_total:
                score += 0.3
        line_sims = []
        for il in ex.line_items:
            sims = [text_similarity(il.description, pl.item_description) for pl in po.lines]
            if sims:
                line_sims.append(max(sims))
        if line_sims:
            score += 0.4 * (sum(line_sims) / len(line_sims))
        out.append({"po_number": po.po_number, "score": round(score, 2), "remaining": str(bal["remaining_before"]), "currency": po.currency})
    out.sort(key=lambda c: -c["score"])
    return out[:3]


# ------------------------------------------------------------------ balances
def po_balance(db: Session, po: PurchaseOrder, exclude_invoice_id: int | None = None) -> dict:
    """authorized_total minus the sum of APPROVED invoices on this PO (optionally excluding one invoice)."""
    q = select(Invoice).where(Invoice.po_id == po.id, Invoice.final_decision == "APPROVED")
    if exclude_invoice_id is not None:
        q = q.where(Invoice.id != exclude_invoice_id)
    approved = list(db.scalars(q))
    used = sum((i.total_amount or ZERO for i in approved), ZERO)
    return {
        "authorized_total": po.authorized_total,
        "approved_total": q2(used),
        "remaining_before": q2(po.authorized_total - used),
        "approved_invoices": [{"id": i.id, "invoice_number": i.invoice_number, "total": str(i.total_amount)} for i in approved],
    }


def reconcile_po(db: Session, po: PurchaseOrder) -> None:
    """Recompute the cached remaining balance and status from approved invoices (source of truth)."""
    bal = po_balance(db, po)
    po.remaining_balance = bal["remaining_before"]
    if po.status != "CLOSED":
        if bal["approved_total"] <= 0:
            po.status = "OPEN"
        elif bal["remaining_before"] <= 0:
            po.status = "FULLY_INVOICED"
        else:
            po.status = "PARTIALLY_INVOICED"


# ------------------------------------------------------------------ line matching
@dataclass
class LineMatchResult:
    lines: list[dict] = field(default_factory=list)
    all_mapped: bool = False
    expected_subtotal: Decimal | None = None
    expected_tax: Decimal | None = None
    expected_total: Decimal | None = None
    flagged: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "lines": self.lines, "all_mapped": self.all_mapped,
            "expected_subtotal": None if self.expected_subtotal is None else str(self.expected_subtotal),
            "expected_tax": None if self.expected_tax is None else str(self.expected_tax),
            "expected_total": None if self.expected_total is None else str(self.expected_total),
            "flagged": self.flagged,
        }


MAPPED = {"MATCHED", "PRICE_MISMATCH", "QTY_EXCEEDED"}


def _prior_qty(db: Session, po: PurchaseOrder, exclude_invoice_id: int | None) -> dict[int, Decimal]:
    q = (
        select(InvoiceLine)
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .where(Invoice.final_decision == "APPROVED", Invoice.po_id == po.id)
    )
    if exclude_invoice_id is not None:
        q = q.where(Invoice.id != exclude_invoice_id)
    used: dict[int, Decimal] = {}
    for il in db.scalars(q):
        if il.matched_po_line_id and il.quantity:
            used[il.matched_po_line_id] = used.get(il.matched_po_line_id, ZERO) + il.quantity
    return used


def match_lines(db: Session, ex: ExtractedInvoice, po: PurchaseOrder | None, settings: Settings,
                exclude_invoice_id: int | None = None) -> LineMatchResult:
    res = LineMatchResult()
    if po is None or not ex.line_items:
        return res
    prior = _prior_qty(db, po, exclude_invoice_id)
    po_lines: list[POLine] = list(po.lines)
    billed_now: dict[int, Decimal] = {}
    exp_sub = ZERO
    exp_tax = ZERO

    for idx, il in enumerate(ex.line_items, 1):
        entry = {
            "index": idx, "description": il.description, "status": "UNMATCHED", "po_line_id": None, "po_description": None,
            "score": 0.0, "invoice_qty": None if il.quantity is None else str(il.quantity),
            "invoice_unit_price": None if il.unit_price is None else str(il.unit_price),
            "invoice_line_total": None if il.line_total is None else str(il.line_total),
            "po_unit_price": None, "price_variance_pct": None, "po_qty_remaining": None, "note": "",
        }
        # rank PO lines
        ranked = []
        for pl in po_lines:
            if il.sku and pl.sku and il.sku.upper() == pl.sku.upper():
                s = 1.0
            elif pl.sku and il.description and pl.sku.upper() in il.description.upper():
                s = 0.98
            else:
                s = text_similarity(il.description, pl.item_description)
            ranked.append((s, pl))
        ranked.sort(key=lambda t: -t[0])
        best_s, best = ranked[0] if ranked else (0.0, None)
        second_s = ranked[1][0] if len(ranked) > 1 else 0.0
        entry["score"] = round(best_s, 3)

        if il.quantity is None or il.unit_price is None:
            entry["status"] = "INCOMPLETE" if best_s >= 0.55 else "UNMATCHED"
            entry["note"] = "Quantity or unit price is not stated on this line, so it cannot be compared to the PO."
            if best_s < 0.55 and il.line_total is not None:
                combo = _bundle_combo(po_lines, il.line_total, settings)
                if combo:
                    entry["status"] = "BUNDLED"
                    entry["note"] = ("Bundled charge: the amount equals the sum of PO lines "
                                     + ", ".join(combo) + ", but the invoice does not itemise them.")
        elif best is None or best_s < 0.55:
            entry["status"] = "UNMATCHED"
            entry["note"] = "No PO line is similar enough to this description."
            if il.line_total is not None:
                combo = _bundle_combo(po_lines, il.line_total, settings)
                if combo:
                    entry["status"] = "BUNDLED"
                    entry["note"] = "Bundled charge equals the sum of PO lines " + ", ".join(combo) + "."
        elif best_s - second_s < 0.05 and second_s >= 0.55 and best_s < 0.98:
            entry["status"] = "AMBIGUOUS"
            entry["note"] = f"Description fits both '{best.item_description}' and '{ranked[1][1].item_description}'."
        else:
            entry["po_line_id"] = best.id
            entry["po_description"] = best.item_description
            entry["po_unit_price"] = str(best.unit_price)
            ok, pct, diff = within_tolerance(il.unit_price, best.unit_price, settings.tolerance_pct, settings.tolerance_abs)
            entry["price_variance_pct"] = str(pct)
            entry["price_diff"] = str(diff)
            billed_now[best.id] = billed_now.get(best.id, ZERO) + il.quantity
            remaining_qty = best.quantity - prior.get(best.id, ZERO)
            entry["po_qty_remaining"] = str(remaining_qty)
            if billed_now[best.id] > remaining_qty:
                entry["status"] = "QTY_EXCEEDED"
                entry["note"] = f"Billed quantity {billed_now[best.id]} exceeds the remaining PO quantity {remaining_qty}."
            elif not ok:
                entry["status"] = "PRICE_MISMATCH"
                entry["note"] = f"Unit price {il.unit_price} differs from the PO price {best.unit_price} by {pct}% (tolerance {settings.tolerance_pct}%)."
            else:
                entry["status"] = "MATCHED"
                entry["note"] = "Matches PO line." if pct == 0 else f"Matches PO line; price differs by {pct}% (within tolerance)."
            # expected value of what was billed, at PO prices and PO tax
            base = il.quantity * best.unit_price
            exp_sub += base
            exp_tax += base * best.tax_rate / 100
        res.lines.append(entry)

    res.all_mapped = all(l["status"] in MAPPED for l in res.lines)
    res.flagged = [f"Line {l['index']}: {l['status']}" for l in res.lines if l["status"] not in ("MATCHED",)]
    if res.all_mapped:
        res.expected_subtotal = q2(exp_sub)
        res.expected_tax = q2(exp_tax)
        res.expected_total = q2(exp_sub + exp_tax)
    return res


def _bundle_combo(po_lines: list[POLine], amount: Decimal, settings: Settings) -> list[str] | None:
    if len(po_lines) < 2 or len(po_lines) > 14:
        return None
    amounts = [(pl, pl.quantity * pl.unit_price) for pl in po_lines]
    for r in range(2, min(6, len(amounts)) + 1):
        for combo in combinations(amounts, r):
            if abs(sum(a for _, a in combo) - amount) <= settings.rounding_tolerance:
                return [pl.item_description for pl, _ in combo]
    return None
