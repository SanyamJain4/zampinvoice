"""Load vendors, POs, PO lines and approved invoice history from sample_data/*.csv (idempotent reset)."""
from __future__ import annotations

import csv
import shutil
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.session import Base, engine
from app.models.models import AuditEvent, Invoice, InvoiceLine, POLine, PurchaseOrder, Vendor
from app.services.common import norm_invoice_number
from app.services.po_matcher import reconcile_po

D = Decimal


def _rows(path: Path):
    with open(path, newline="", encoding="utf-8") as fh:
        yield from csv.DictReader(fh)


def seed_from_csv(db: Session, sample_dir: Path) -> dict:
    vendors = {}
    for r in _rows(sample_dir / "vendors.csv"):
        v = Vendor(vendor_id=r["vendor_id"], legal_name=r["legal_name"], aliases=[a for a in r["aliases"].split("|") if a],
                   tax_id=r["tax_id"], country=r["country"], approval_status=r["approval_status"])
        db.add(v)
        vendors[v.vendor_id] = v
    db.flush()

    pos = {}
    for r in _rows(sample_dir / "purchase_orders.csv"):
        po = PurchaseOrder(po_number=r["po_number"], vendor_id=vendors[r["vendor_id"]].id, issue_date=date.fromisoformat(r["issue_date"]),
                           currency=r["currency"], subtotal=D(r["subtotal"]), tax_amount=D(r["tax_amount"]),
                           authorized_total=D(r["authorized_total"]), remaining_balance=D(r["authorized_total"]),
                           status=r["status"], description=r["description"])
        db.add(po)
        pos[po.po_number] = po
    db.flush()

    po_lines: dict[tuple[str, int], POLine] = {}
    for r in _rows(sample_dir / "po_lines.csv"):
        q, p, t = D(r["quantity"]), D(r["unit_price"]), D(r["tax_rate"])
        pl = POLine(po_id=pos[r["po_number"]].id, line_no=int(r["line_no"]), item_description=r["item_description"], sku=r["sku"],
                    quantity=q, unit_price=p, tax_rate=t, authorized_amount=(q * p * (1 + t / 100)).quantize(D("0.01")))
        db.add(pl)
        po_lines[(r["po_number"], pl.line_no)] = pl
    db.flush()

    n_hist = 0
    for r in _rows(sample_dir / "history_invoices.csv"):
        d = date.fromisoformat(r["invoice_date"])
        pl = po_lines[(r["po_number"], int(r["po_line_no"]))]
        inv = Invoice(
            invoice_number=r["invoice_number"], invoice_number_norm=norm_invoice_number(r["invoice_number"]),
            vendor_id=vendors[r["vendor_id"]].id, po_id=pos[r["po_number"]].id, vendor_name_raw=vendors[r["vendor_id"]].legal_name,
            po_number_raw=r["po_number"], invoice_date=d, currency=r["currency"], subtotal=D(r["subtotal"]), tax_amount=D(r["tax_amount"]),
            total_amount=D(r["total_amount"]), source="HISTORY", processing_status="PROCESSED", final_decision="APPROVED",
            decision_reason="Historical approved invoice (seeded).", decision_source="AUTO",
            decision_detail={"status": "APPROVED", "main_reason": "Historical approved invoice (seeded).", "detailed_reasons": []},
            created_at=datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc), decided_at=datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc),
            original_filename="(historical record - no PDF)",
        )
        inv.lines.append(InvoiceLine(line_no=1, description=pl.item_description, sku=pl.sku, quantity=D(r["quantity"]), unit_price=pl.unit_price,
                                     tax_rate=pl.tax_rate, line_total=D(r["subtotal"]), matched_po_line_id=pl.id))
        db.add(inv)
        n_hist += 1
    db.flush()
    for po in pos.values():
        reconcile_po(db, po)
    db.commit()
    return {"vendors": len(vendors), "purchase_orders": len(pos), "po_lines": len(po_lines), "history_invoices": n_hist}


def reset_database(db: Session | None = None, sample_dir: Path | None = None, clear_uploads: bool = True) -> dict:
    """Drop everything, recreate the schema and reseed the master data."""
    settings = get_settings()
    sample_dir = sample_dir or settings.sample_dir
    if db is not None:
        db.close()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    if clear_uploads and settings.upload_dir.exists():
        for p in settings.upload_dir.glob("*"):
            if p.is_file():
                p.unlink()
    from app.database.session import SessionLocal

    with SessionLocal() as s:
        counts = seed_from_csv(s, sample_dir)
        s.add(AuditEvent(event_type="DATABASE_SEEDED", actor="system", new_value=counts, reason="Master data loaded from sample_data CSVs"))
        s.commit()
    return counts


def is_seeded(db: Session) -> bool:
    return db.scalar(select(Vendor.id).limit(1)) is not None
