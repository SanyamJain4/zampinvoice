"""Structured extraction schema + lenient-in / strict-out normalisation.

The model (or heuristic parser) may return numbers as "1,00,000.00" or dates as "15/11/2026";
`normalize_raw` converts everything to Decimal / ISO dates, records warnings for anything it could
not parse (it never invents a value), and the result is validated by Pydantic.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

REQUIRED_FIELDS = ["vendor_name", "invoice_number", "invoice_date", "po_number", "currency", "grand_total"]

MONEY_FIELDS = ["subtotal", "discount", "shipping", "tax_amount", "grand_total"]
_NULLS = {"", "null", "none", "n/a", "na", "-", "--", "—", "nil", "not available", "unknown"}
_CURRENCY_MAP = {"₹": "INR", "RS": "INR", "RS.": "INR", "INR": "INR", "$": "USD", "US$": "USD", "USD": "USD",
                 "€": "EUR", "EUR": "EUR", "£": "GBP", "GBP": "GBP", "AED": "AED", "SGD": "SGD"}


class Evidence(BaseModel):
    page: int | None = None
    snippet: str | None = None


class ExtractedLine(BaseModel):
    model_config = ConfigDict(extra="ignore")
    description: str | None = None
    sku: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    tax_rate: Decimal | None = None
    line_total: Decimal | None = None


class ExtractedInvoice(BaseModel):
    model_config = ConfigDict(extra="ignore")
    vendor_name: str | None = None
    vendor_tax_id: str | None = None
    vendor_address: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    po_number: str | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    discount: Decimal | None = None
    shipping: Decimal | None = None
    tax_amount: Decimal | None = None
    grand_total: Decimal | None = None
    line_items: list[ExtractedLine] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence: dict[str, Evidence] = Field(default_factory=dict)

    def compute_missing(self) -> list[str]:
        return [f for f in REQUIRED_FIELDS if getattr(self, f) in (None, "")]


def to_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    s = str(value).strip()
    if s.lower() in _NULLS:
        return None
    neg = (s.startswith("(") and s.endswith(")")) or bool(re.match(r"^[^\d]*-\s*\d", s))
    m = re.search(r"\d[\d,]*(?:\.\d+)?", s)  # first numeric token; ignores "Rs.", "INR", "$" prefixes
    if not m:
        return None
    try:
        d = Decimal(m.group(0).replace(",", ""))
    except InvalidOperation:
        return None
    return -d if neg else d


_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip().rstrip(".")
    if s.lower() in _NULLS:
        return None
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        return _safe_date(int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", s)  # day-first (India/EU convention)
    if m:
        return _safe_date(int(m[3]), int(m[2]), int(m[1]))
    m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?[\s\-,]+([A-Za-z]{3,9})\.?[\s\-,]+(\d{4})", s)
    if m and m[2][:3].lower() in _MONTHS:
        return _safe_date(int(m[3]), _MONTHS[m[2][:3].lower()], int(m[1]))
    m = re.fullmatch(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", s)
    if m and m[1][:3].lower() in _MONTHS:
        return _safe_date(int(m[3]), _MONTHS[m[1][:3].lower()], int(m[2]))
    return None


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _clean_str(v: Any) -> str | None:
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return None if s.lower() in _NULLS else s


def normalize_currency(v: Any) -> str | None:
    s = _clean_str(v)
    if not s:
        return None
    key = s.upper().strip()
    if key in _CURRENCY_MAP:
        return _CURRENCY_MAP[key]
    return key if re.fullmatch(r"[A-Z]{3}", key) else None


def normalize_raw(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Coerce a raw extraction dict into clean types. Unparseable values become None + a warning."""
    warnings: list[str] = list(raw.get("warnings") or [])
    out: dict[str, Any] = {}
    for f in ("vendor_name", "vendor_address", "invoice_number"):
        out[f] = _clean_str(raw.get(f))
    tid = _clean_str(raw.get("vendor_tax_id"))
    out["vendor_tax_id"] = re.sub(r"[\s]", "", tid).upper() if tid else None
    po = _clean_str(raw.get("po_number"))
    out["po_number"] = po.upper() if po else None
    out["currency"] = normalize_currency(raw.get("currency"))
    if raw.get("currency") not in (None, "") and out["currency"] is None and _clean_str(raw.get("currency")):
        warnings.append(f"Currency '{raw.get('currency')}' is not a recognised ISO code and was ignored.")
    for f in ("invoice_date", "due_date"):
        v = raw.get(f)
        d = parse_date(v)
        if d is None and _clean_str(v):
            warnings.append(f"Could not read {f.replace('_', ' ')} '{v}'; treated as missing.")
        out[f] = d.isoformat() if d else None
    for f in MONEY_FIELDS:
        v = raw.get(f)
        d = to_decimal(v)
        if d is None and _clean_str(v):
            warnings.append(f"Could not read {f.replace('_', ' ')} '{v}'; treated as missing.")
        out[f] = str(d) if d is not None else None
    lines = []
    for item in raw.get("line_items") or []:
        if not isinstance(item, dict):
            continue
        ln = {
            "description": _clean_str(item.get("description")),
            "sku": _clean_str(item.get("sku")),
            "quantity": None, "unit_price": None, "tax_rate": None, "line_total": None,
        }
        for k in ("quantity", "unit_price", "tax_rate", "line_total"):
            d = to_decimal(item.get(k))
            ln[k] = str(d) if d is not None else None
        if any(ln[k] is not None for k in ("description", "quantity", "unit_price", "line_total")):
            lines.append(ln)
    out["line_items"] = lines
    ev = {}
    for k, v in (raw.get("evidence") or {}).items():
        if isinstance(v, dict):
            page = v.get("page")
            ev[k] = {"page": page if isinstance(page, int) else None, "snippet": _clean_str(v.get("snippet"))}
    out["evidence"] = ev
    out["warnings"] = warnings
    out["missing_fields"] = []
    return out, warnings


def build_extracted(raw: dict[str, Any]) -> ExtractedInvoice:
    clean, _ = normalize_raw(raw)
    inv = ExtractedInvoice.model_validate(clean)
    inv.missing_fields = inv.compute_missing()
    for f in inv.missing_fields:
        msg = f"{f.replace('_', ' ').capitalize()} was not found in the document."
        if msg not in inv.warnings:
            inv.warnings.append(msg)
    return inv
