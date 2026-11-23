"""Offline, rule-based invoice parser.

Used only when no LLM API key is configured (LLM_PROVIDER=heuristic or auto without keys). It reads
the *actual* text of the uploaded document, never invents a value (returns None when a field is not
found) and records evidence (page + line) for every field it returns. It is intentionally simpler than
the LLM path and is clearly labelled as such in the run timeline.
"""
from __future__ import annotations

import re

from app.schemas.extraction import parse_date, to_decimal

DATE_RX = (
    r"(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"
    r"|\d{1,2}[-/.]\d{1,2}[-/.]\d{4}"
    r"|\d{1,2}(?:st|nd|rd|th)?[\s\-]+[A-Za-z]{3,9}\.?,?[\s\-]+\d{4}"
    r"|[A-Za-z]{3,9}\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})"
)
AMOUNT_RX = re.compile(r"(?<![\d.,])-?\d[\d,]*\.\d{2}(?!\d)")
COMPANY_WORDS = (
    r"Pvt\.?|Private|Ltd\.?|Limited|LLP|LLC|Inc\.?|Corp\.?|Corporation|GmbH|Co\.|Company|Traders|Agency|Group|"
    r"Services|Solutions|Systems|Technologies|Industries|Enterprises|Logistics|Supplies|Consulting|Packaging|Parts|Associates"
)
COMPANY_RX = re.compile(rf"\b(?:{COMPANY_WORDS})(?=\W|$)", re.I)
ROW_RX = re.compile(
    r"""^(?:(?P<no>\d{1,3})[.)]?\s+)?
        (?:(?P<sku>[A-Z]{2,6}-[A-Z0-9][A-Z0-9\-]*)\s+)?
        (?P<desc>.+?)\s+
        (?P<qty>\d+(?:\.\d+)?)\s+
        (?:(?:nos|pcs|hrs?|hours?|units?|ea|each|lic|mo|months?|kg|sets?|pkts?|box|boxes)\.?\s+)?
        (?:(?:INR|Rs\.?|₹|USD|US\$|\$|EUR|€)\s*)?(?P<unit>[\d,]+\.\d{2})\s+
        (?:(?P<rate>\d+(?:\.\d+)?)\s*%\s+)?
        (?:(?:INR|Rs\.?|₹|USD|US\$|\$|EUR|€)\s*)?(?P<total>[\d,]+\.\d{2})$""",
    re.X | re.I,
)
BUNDLE_RX = re.compile(
    r"""^(?:(?P<no>\d{1,3})[.)]?\s+)?(?P<desc>[A-Za-z].+?)\s{2,}
        (?:(?P<rate>\d+(?:\.\d+)?)\s*%\s+)?
        (?:(?:INR|Rs\.?|₹|USD|US\$|\$|EUR|€)\s*)?(?P<total>[\d,]+\.\d{2})$""",
    re.X | re.I,
)
TOTALS_START = re.compile(
    r"^(?:sub\s*-?\s*total|total\b|taxable|grand\s*total|discount|shipping|freight|c?gst|s?gst|igst|vat|tax\b|"
    r"amount\s+(?:in\s+words|due|payable)|notes?\b|payment\s+terms|bank\b|terms\b)",
    re.I,
)
HEADER_RX = re.compile(r"(description|particulars|item|service)", re.I)
HEADER_AMT_RX = re.compile(r"(amount|total|price|value)", re.I)
KNOWN_CURRENCIES = {"INR", "USD", "EUR", "GBP", "AED", "SGD", "AUD", "CAD", "JPY", "CNY"}
NOT_A_NAME = re.compile(r"description|particulars|qty|quantity|amount|unit\s*price|\bhsn\b|goods|invoice|bill\s*to|payment\s*terms|computer\s*generated", re.I)
COMPANY_SQUASHED = re.compile(r"(?:Pvt|Ltd|LLP|LLC|Inc|Limited|Agency|Traders|Logistics|Consulting|Packaging|Solutions|Services|Technologies|Industries|Enterprises)", re.I)
BAD_VALUES = {"invoice", "date", "dated", "number", "no", "due", "po", "gst", "gstin", "tax", "bill", "total", "ref", "reference"}


def _first_amount(line: str) -> str | None:
    found = AMOUNT_RX.findall(line)
    return found[-1] if found else None


class _Doc:
    def __init__(self, pages: list[list[str]]):
        self.rows: list[tuple[int, str]] = [(pi + 1, ln) for pi, lines in enumerate(pages) for ln in lines]

    def find(self, label_rx: str, value_rx: str, flags=re.I, skip=None):
        """Find `label <sep> value` on one line, else label at end of line + value on the next line."""
        lab = re.compile(label_rx, flags)
        val_same = re.compile(rf"(?:{label_rx})\s*[:#\-.]?\s*(?P<v>{value_rx})", flags)
        val_next = re.compile(rf"^(?P<v>{value_rx})", flags)
        for i, (page, line) in enumerate(self.rows):
            if skip and skip.search(line):
                continue
            m = val_same.search(line)
            if m and m.group("v").lower().strip(":#.") not in BAD_VALUES:
                return m.group("v").strip(), page, line
            lm = lab.search(line)
            if lm and not line[lm.end():].strip(" :#-.") and i + 1 < len(self.rows):
                nxt = self.rows[i + 1][1]
                m2 = val_next.match(nxt.strip())
                if m2 and m2.group("v").lower() not in BAD_VALUES:
                    return m2.group("v").strip(), page, nxt
        return None


def extract(pages: list[list[str]], buyer_name: str = "", buyer_tax_id: str = "") -> dict:
    d = _Doc(pages)
    ev: dict[str, dict] = {}
    out: dict = {"line_items": [], "warnings": []}

    def put(field: str, hit):
        if hit:
            value, page, line = hit
            out[field] = value
            ev[field] = {"page": page, "snippet": line[:160]}
        else:
            out.setdefault(field, None)

    # Invoice number -- must contain a digit so "Invoice Date" is never read as a number.
    put("invoice_number", d.find(
        r"(?:tax\s+)?invoice\s*(?:no\.?|number|num|#|id)|inv\.?\s*(?:no\.?|#)|bill\s*(?:no\.?|number)",
        r"(?=[A-Z0-9\-/_.]*\d)[A-Z0-9][A-Z0-9\-/_.]{2,}",
    ))
    # Dates
    hit = d.find(r"invoice\s*date|date\s*of\s*(?:issue|invoice)|issue\s*date|bill\s*date|dated", DATE_RX)
    if not hit:
        hit = d.find(r"(?<![A-Za-z])date", DATE_RX, skip=re.compile(r"due|po\s*date|order\s*date", re.I))
    put("invoice_date", hit)
    put("due_date", d.find(r"due\s*date|payment\s*due(?:\s*date)?|due\s*on|pay\s*by", DATE_RX))
    for f in ("invoice_date", "due_date"):
        if out.get(f):
            parsed = parse_date(out[f])
            out[f] = parsed.isoformat() if parsed else None

    # PO number
    po = d.find(
        r"\bP\.?\s?O\.?\s*(?:no\.?|number|#|ref(?:erence)?)?|purchase\s*order(?:\s*(?:no\.?|number|ref(?:erence)?))?|your\s*order\s*(?:no\.?|ref)?",
        r"[A-Z]{0,4}-?\d{2,}[A-Z0-9\-/]*",
    )
    if not po:
        for page, line in d.rows:
            m = re.search(r"\bPO[-\s]?\d{2,}\b", line, re.I)
            if m:
                po = (m.group(0), page, line)
                break
    put("po_number", po)
    if out.get("po_number"):
        out["po_number"] = re.sub(r"^PO\s*-?\s*", "PO-", out["po_number"].upper()) if re.match(r"(?i)^PO\s*-?\s*\d", out["po_number"]) else out["po_number"].upper()

    # Currency
    cur = d.find(r"currency", r"[A-Z]{3}")
    currency = cur[0].upper() if cur else None
    if currency not in KNOWN_CURRENCIES:
        currency = None
    if not currency:
        blob = " ".join(l for _, l in d.rows)
        counts = {
            "INR": len(re.findall(r"\bINR\b|₹|\bRs\.?(?=\s*\d)", blob)),
            "USD": len(re.findall(r"\bUSD\b|US\$|\$", blob)),
            "EUR": len(re.findall(r"\bEUR\b|€", blob)),
            "GBP": len(re.findall(r"\bGBP\b|£", blob)),
        }
        best = max(counts, key=counts.get)
        currency = best if counts[best] else None
    out["currency"] = currency

    # Totals live after the line-item table (so a line item called "Freight services" is never read as shipping).
    totals_from = 0
    seen_header = False
    for idx, (_, line) in enumerate(d.rows):
        s = line.strip()
        if not seen_header:
            seen_header = bool(HEADER_RX.search(s) and HEADER_AMT_RX.search(s) and not AMOUNT_RX.search(s))
            continue
        if TOTALS_START.match(s) and not ROW_RX.match(s):
            totals_from = idx
            break

    # Totals (search the lines; take the last amount on the matching line)
    def amount_for(label_rx: str, exclude: str | None = None, prefer_last: bool = True):
        lab = re.compile(label_rx, re.I)
        ex = re.compile(exclude, re.I) if exclude else None
        hits = []
        for page, line in d.rows[totals_from:]:
            if lab.search(line) and not (ex and ex.search(line)):
                amt = _first_amount(line)
                if amt:
                    hits.append((amt, page, line))
        if not hits:
            return None
        return hits[-1] if prefer_last else hits[0]

    put("subtotal", amount_for(r"^\s*(?:sub\s*-?\s*total|total\s*before\s*tax|taxable\s*(?:value|amount)|net\s*amount|amount\s*before\s*tax)"))
    put("discount", amount_for(r"^\s*(?:less\s*:?\s*)?discount"))
    put("shipping", amount_for(r"^\s*(?:shipping|freight|delivery\s*charges?|handling)"))
    # Tax: prefer an explicit "Total GST/Tax" line, else sum CGST+SGST/IGST/GST/VAT lines.
    tax_total = amount_for(r"^\s*total\s*(?:gst|tax|vat|igst)", exclude=r"taxable")
    if tax_total:
        put("tax_amount", tax_total)
    else:
        parts = []
        for page, line in d.rows[totals_from:]:
            if re.match(r"^\s*(?:c?gst|s?gst|igst|utgst|vat|sales\s*tax|tax)\b", line, re.I) and not re.search(r"taxable|total|no\b|id\b|number", line, re.I):
                amt = _first_amount(line)
                if amt:
                    parts.append((amt, page, line))
        if parts:
            total = sum(to_decimal(p[0]) for p in parts)
            out["tax_amount"] = str(total)
            ev["tax_amount"] = {"page": parts[0][1], "snippet": " | ".join(p[2][:60] for p in parts)[:160]}
        else:
            out["tax_amount"] = None
    gt = amount_for(r"^\s*(?:grand\s*total|total\s*(?:amount\s*)?(?:due|payable)|amount\s*(?:due|payable)|balance\s*due|invoice\s*total|total\s*invoice\s*value)")
    if not gt:
        gt = amount_for(r"^\s*total\b(?!\s*(?:tax|gst|vat|igst|taxable|discount))", exclude=r"sub\s*-?\s*total")
    put("grand_total", gt)

    # Vendor identity
    buyer_l = buyer_name.lower()
    vendor_line = None
    hit = d.find(r"(?:billed\s*by|sold\s*by|vendor|supplier|from|seller)\s*(?:name)?", r"[A-Za-z][^\n]{3,80}")
    if hit and COMPANY_RX.search(hit[0]) and buyer_l not in hit[0].lower():
        vendor_line = hit
    if not vendor_line:
        for idx, (page, line) in enumerate(d.rows[:40]):
            low = line.lower()
            if re.match(r"^(bill(?:ed)?\s*to|ship\s*to|sold\s*to|customer|buyer|consignee)", low):
                continue
            if buyer_l and buyer_l in low:
                continue
            for seg in re.split(r"\s{2,}", line):
                if NOT_A_NAME.search(seg) or not re.match(r"^[A-Z0-9]", seg) or len(seg) >= 90:
                    continue
                # normal names, or OCR output whose spaces were lost ("FusionMarketingAgency")
                if COMPANY_RX.search(seg) or (" " not in seg and len(seg) > 12 and COMPANY_SQUASHED.search(seg)):
                    vendor_line = (seg, page, line)
                    break
            if vendor_line:
                break
    if vendor_line:
        name = re.sub(r"^(?:billed\s*by|sold\s*by|vendor|supplier|from|seller)\s*[:\-]?\s*", "", vendor_line[0], flags=re.I).strip(" :-")
        out["vendor_name"] = name
        ev["vendor_name"] = {"page": vendor_line[1], "snippet": vendor_line[2][:160]}
    else:
        out["vendor_name"] = None

    # Tax id (GSTIN / EIN / labelled), never the buyer's
    tax_ids: list[tuple[str, int, str]] = []
    for page, line in d.rows:
        for m in re.finditer(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b|\b\d{2}-\d{7}\b", line):
            tax_ids.append((m.group(0), page, line))
        m = re.search(r"(?:tax\s*id|gstin|gst\s*no\.?|vat\s*(?:no\.?|id)|ein|tin)\s*[:#]?\s*([A-Z0-9\-]{8,20})", line, re.I)
        if m and re.search(r"\d", m.group(1)):
            tax_ids.append((m.group(1), page, line))
    tax_ids = [t for t in tax_ids if t[0].upper() != buyer_tax_id.upper()]
    if tax_ids:
        out["vendor_tax_id"] = tax_ids[0][0]
        ev["vendor_tax_id"] = {"page": tax_ids[0][1], "snippet": tax_ids[0][2][:160]}
    else:
        out["vendor_tax_id"] = None
    out["vendor_address"] = None

    # Line items
    in_table = False
    items: list[dict] = []
    for page, line in d.rows:
        low = line.strip()
        if not in_table:
            if HEADER_RX.search(low) and HEADER_AMT_RX.search(low) and not AMOUNT_RX.search(low):
                in_table = True
            continue
        if HEADER_RX.search(low) and HEADER_AMT_RX.search(low) and not AMOUNT_RX.search(low):
            continue  # repeated header on a continuation page
        if re.match(r"^(page\s+\d+|continued|carried|brought)", low, re.I):
            continue
        m = ROW_RX.match(low)
        if not m and TOTALS_START.match(low):
            in_table = False
            continue
        if m:
            items.append({
                "description": m.group("desc").strip(" -"), "sku": m.group("sku"),
                "quantity": m.group("qty"), "unit_price": m.group("unit"),
                "tax_rate": m.group("rate"), "line_total": m.group("total"), "_page": page,
            })
            continue
        m = BUNDLE_RX.match(low)
        if m:
            items.append({
                "description": m.group("desc").strip(" -"), "sku": None, "quantity": None,
                "unit_price": None, "tax_rate": m.group("rate"), "line_total": m.group("total"), "_page": page,
            })
    out["line_items"] = items
    if items:
        ev["line_items"] = {"page": items[0]["_page"], "snippet": f"{len(items)} table row(s) parsed"}
    for it in items:
        it.pop("_page", None)
    out["evidence"] = ev
    if not items:
        out["warnings"].append("No line-item table could be parsed from the document.")
    return out
