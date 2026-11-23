"""Vendor verification: tax id > legal name > alias > normalised name > cautious fuzzy suggestion."""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Vendor
from app.schemas.extraction import ExtractedInvoice
from app.services.common import norm_company, norm_tax_id

FUZZY_THRESHOLD = 0.82


@dataclass
class VendorMatch:
    # VERIFIED_APPROVED | VERIFIED_INACTIVE | BLOCKED | UNRECOGNIZED | AMBIGUOUS
    status: str
    vendor: Vendor | None = None
    method: str | None = None
    message: str = ""
    candidates: list[dict] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return self.status in ("VERIFIED_APPROVED", "VERIFIED_INACTIVE", "BLOCKED") and self.vendor is not None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "method": self.method,
            "message": self.message,
            "vendor": None if not self.vendor else {
                "id": self.vendor.id, "vendor_id": self.vendor.vendor_id, "legal_name": self.vendor.legal_name,
                "approval_status": self.vendor.approval_status, "tax_id": self.vendor.tax_id,
            },
            "candidates": self.candidates,
        }


def _status_for(v: Vendor) -> str:
    return {"APPROVED": "VERIFIED_APPROVED", "INACTIVE": "VERIFIED_INACTIVE", "BLOCKED": "BLOCKED"}.get(
        v.approval_status, "UNRECOGNIZED"
    )


def _names(v: Vendor) -> list[str]:
    return [v.legal_name, *(v.aliases or [])]


def match_vendor(db: Session, ex: ExtractedInvoice) -> VendorMatch:
    vendors = list(db.scalars(select(Vendor)))
    name = (ex.vendor_name or "").strip()
    name_l = name.lower()
    name_n = norm_company(name)
    tid = norm_tax_id(ex.vendor_tax_id)

    if not name and not tid:
        return VendorMatch("UNRECOGNIZED", message="The invoice does not state a vendor name or tax identifier.")

    # name-based candidates (used for conflict detection as well as matching)
    by_exact = [v for v in vendors if name and v.legal_name.lower() == name_l]
    by_alias = [v for v in vendors if name and name_l in [a.lower() for a in (v.aliases or [])]]
    by_norm = [v for v in vendors if name_n and any(norm_company(n) == name_n for n in _names(v))]
    name_hits = {v.id: v for v in by_exact + by_alias + by_norm}

    # 1. tax identifier
    if tid:
        tv = [v for v in vendors if norm_tax_id(v.tax_id) == tid]
        if len(tv) == 1:
            v = tv[0]
            if name_hits and v.id not in name_hits:
                other = next(iter(name_hits.values()))
                return VendorMatch(
                    "AMBIGUOUS", message=f"The tax ID on the invoice belongs to {v.legal_name}, but the vendor name "
                    f"matches {other.legal_name}. This inconsistency needs human verification.",
                    candidates=[_cand(v, 1.0, "tax id"), _cand(other, 1.0, "name")],
                )
            if not name_hits and name:
                sim = max(SequenceMatcher(None, name_n, norm_company(n)).ratio() for n in _names(v))
                if sim < 0.6:
                    return VendorMatch(
                        "AMBIGUOUS", message=f"The tax ID belongs to {v.legal_name}, but the invoice names "
                        f"'{name}'. Name and tax ID disagree.", candidates=[_cand(v, sim, "tax id")],
                    )
            return VendorMatch(_status_for(v), v, "TAX_ID", f"Tax ID {ex.vendor_tax_id} matches {v.legal_name}.")
        if len(tv) > 1:
            return VendorMatch("AMBIGUOUS", message="The tax ID matches several vendor records.", candidates=[_cand(v, 1.0, "tax id") for v in tv])

    # 2-4. name based
    def with_tax_check(v: Vendor, method: str) -> VendorMatch:
        if tid and v.tax_id and norm_tax_id(v.tax_id) != tid:
            return VendorMatch(
                "AMBIGUOUS", message=f"The vendor name matches {v.legal_name}, but the tax ID on the invoice "
                f"({ex.vendor_tax_id}) differs from the registered one.", candidates=[_cand(v, 1.0, method.lower())],
            )
        return VendorMatch(_status_for(v), v, method, f"Matched {v.legal_name} by {method.lower().replace('_', ' ')}.")

    if len(by_exact) == 1:
        return with_tax_check(by_exact[0], "LEGAL_NAME")
    if len(by_alias) == 1 and not by_exact:
        return with_tax_check(by_alias[0], "ALIAS")
    if len(name_hits) == 1 and not by_exact and not by_alias:
        return with_tax_check(next(iter(name_hits.values())), "NORMALIZED_NAME")
    if len(name_hits) > 1:
        return VendorMatch(
            "AMBIGUOUS", message=f"'{name}' could refer to {len(name_hits)} different vendors.",
            candidates=[_cand(v, 1.0, "name") for v in name_hits.values()],
        )

    # 5. cautious fuzzy suggestions (never an automatic match)
    scored = []
    for v in vendors:
        sim = max((SequenceMatcher(None, name_n, norm_company(n)).ratio() for n in _names(v)), default=0)
        if sim >= FUZZY_THRESHOLD:
            scored.append((sim, v))
    scored.sort(key=lambda t: -t[0])
    if scored:
        return VendorMatch(
            "AMBIGUOUS", message=f"'{name}' is not an exact match for any vendor; closest: "
            + ", ".join(f"{v.legal_name} ({s:.0%})" for s, v in scored[:3]) + ". A human must confirm.",
            candidates=[_cand(v, s, "fuzzy") for s, v in scored[:3]],
        )
    return VendorMatch("UNRECOGNIZED", message=f"'{name}' does not match any vendor in the vendor master.")


def _cand(v: Vendor, score: float, basis: str) -> dict:
    return {"vendor_id": v.vendor_id, "legal_name": v.legal_name, "approval_status": v.approval_status, "score": round(score, 3), "basis": basis}
