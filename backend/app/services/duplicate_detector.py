"""Duplicate detection: file hash, exact (vendor + normalised number), suspicious near-duplicates."""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Invoice
from app.schemas.extraction import ExtractedInvoice
from app.services.common import norm_invoice_number
from app.services.vendor_matcher import VendorMatch

DECIDED = ("APPROVED", "NEEDS_REVIEW", "REJECTED")


@dataclass
class DuplicateResult:
    status: str  # NONE | CONFIRMED | SUSPECTED | NOT_CHECKABLE
    kind: str | None = None  # FILE_HASH | EXACT_NUMBER | SUSPICIOUS
    original: Invoice | None = None
    message: str = ""
    matches: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status, "kind": self.kind, "message": self.message, "matches": self.matches,
            "original_invoice_id": self.original.id if self.original else None,
        }


def _brief(i: Invoice, reason: str) -> dict:
    return {
        "invoice_id": i.id, "invoice_number": i.invoice_number, "decision": i.final_decision, "total": None if i.total_amount is None else str(i.total_amount),
        "invoice_date": i.invoice_date.isoformat() if i.invoice_date else None, "reason": reason,
        "source": i.source,
    }


def detect(db: Session, invoice: Invoice, ex: ExtractedInvoice, vendor: VendorMatch) -> DuplicateResult:
    base = select(Invoice).where(
        Invoice.id != invoice.id, Invoice.final_decision.in_(DECIDED), Invoice.duplicate_of_id.is_(None)
    )
    # 1) identical file
    if invoice.file_hash:
        same_file = list(db.scalars(base.where(Invoice.file_hash == invoice.file_hash).order_by(Invoice.id)))
        if same_file:
            o = same_file[0]
            return DuplicateResult(
                "CONFIRMED", "FILE_HASH", o,
                f"This exact file was already processed as invoice #{o.id} ({o.invoice_number or 'no number'}, {o.final_decision}).",
                [_brief(i, "identical file (SHA-256)") for i in same_file],
            )
    num = norm_invoice_number(ex.invoice_number)
    if not vendor.verified:
        return DuplicateResult("NOT_CHECKABLE", message="Duplicate check by invoice number requires a verified vendor.")
    vid = vendor.vendor.id
    # 2) exact vendor + number
    if num:
        exact = list(db.scalars(base.where(Invoice.vendor_id == vid, Invoice.invoice_number_norm == num).order_by(Invoice.id)))
        if exact:
            o = exact[0]
            return DuplicateResult(
                "CONFIRMED", "EXACT_NUMBER", o,
                f"Vendor {vendor.vendor.legal_name} already submitted invoice number {o.invoice_number} "
                f"(record #{o.id}, decision {o.final_decision}).",
                [_brief(i, "same vendor + same invoice number") for i in exact],
            )
    # 3) suspicious: same vendor, same total and (same date or very similar number)
    suspects = []
    if ex.grand_total is not None:
        for i in db.scalars(base.where(Invoice.vendor_id == vid, Invoice.total_amount == ex.grand_total)):
            sim = SequenceMatcher(None, num or "", i.invoice_number_norm or "").ratio() if num else 0
            same_date = ex.invoice_date is not None and i.invoice_date == ex.invoice_date
            if same_date or sim >= 0.8:
                why = []
                if same_date:
                    why.append("same invoice date")
                if sim >= 0.8:
                    why.append(f"similar invoice number ({i.invoice_number})")
                suspects.append(_brief(i, "same vendor and amount, " + " and ".join(why)))
    if suspects:
        return DuplicateResult(
            "SUSPECTED", "SUSPICIOUS", None,
            f"{len(suspects)} earlier invoice(s) from this vendor have the same amount and look similar.", suspects,
        )
    if not num:
        return DuplicateResult("NOT_CHECKABLE", message="No invoice number is available, so exact duplicate detection cannot be completed.")
    return DuplicateResult("NONE", message="No prior invoice with the same vendor and number, and no identical file.")
