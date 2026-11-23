"""Shared helpers: normalisation, similarity, money formatting."""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from difflib import SequenceMatcher

COMPANY_NOISE = {
    "pvt", "private", "ltd", "limited", "llp", "inc", "incorporated", "corp", "corporation", "co", "company",
    "llc", "gmbh", "the", "and", "pte", "plc",
}
STOP = {"and", "the", "of", "for", "a", "an", "to", "with", "per", "on"}
CENT = Decimal("0.01")


def q2(x: Decimal | None) -> Decimal | None:
    return None if x is None else x.quantize(CENT, rounding=ROUND_HALF_UP)


def money(x: Decimal | None, currency: str | None = None) -> str:
    if x is None:
        return "—"
    s = f"{q2(x):,.2f}"
    return f"{currency} {s}" if currency else s


def norm_invoice_number(s: str | None) -> str | None:
    if not s:
        return None
    n = re.sub(r"[^A-Z0-9]", "", s.upper())
    return n or None


def norm_po(s: str | None) -> str | None:
    return re.sub(r"[^A-Z0-9]", "", s.upper()) if s else None


def norm_tax_id(s: str | None) -> str | None:
    return re.sub(r"[^A-Z0-9]", "", s.upper()) if s else None


def norm_company(s: str | None) -> str:
    if not s:
        return ""
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(t for t in s.split() if t not in COMPANY_NOISE)


def tokens(s: str | None) -> set[str]:
    out = set()
    for t in re.findall(r"[a-z0-9]+", (s or "").lower()):
        if t in STOP:
            continue
        if len(t) > 3 and t.endswith("s"):
            t = t[:-1]
        out.add(t)
    return out


def text_similarity(a: str | None, b: str | None) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    jac = len(ta & tb) / len(ta | tb)
    seq = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    blended = 0.5 * jac + 0.5 * seq
    # OCR often drops spaces ("CampaignManagement-Nov"): also compare the squashed alphanumerics.
    sa, sb = re.sub(r"[^a-z0-9]", "", (a or "").lower()), re.sub(r"[^a-z0-9]", "", (b or "").lower())
    squashed = SequenceMatcher(None, sa, sb).ratio() if sa and sb else 0.0
    return round(max(blended, squashed if squashed >= 0.8 else 0.0), 4)


def within_tolerance(actual: Decimal, expected: Decimal, tol_pct: Decimal, tol_abs: Decimal) -> tuple[bool, Decimal, Decimal]:
    """Variance rule: |actual-expected| / expected * 100 <= tol_pct  OR  |actual-expected| <= tol_abs."""
    diff = abs(actual - expected)
    pct = (diff / expected * 100) if expected else (Decimal(0) if diff == 0 else Decimal(100))
    ok = pct <= tol_pct or (tol_abs > 0 and diff <= tol_abs)
    return ok, pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), q2(diff)


def dec(v) -> Decimal | None:
    if v is None or v == "":
        return None
    return v if isinstance(v, Decimal) else Decimal(str(v))
