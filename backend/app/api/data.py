"""Master data, reviews, dashboard, audit, settings, samples and admin endpoints."""
import json
import shutil
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from app.api import serializers as ser
from app.api.invoices import create_invoice_from_file
from app.core.config import get_settings
from app.database.session import get_db
from app.models.models import AuditEvent, Invoice, ProcessingRun, PurchaseOrder, Vendor
from app.services import ai_extractor, ocr_service, po_matcher, seeder

router = APIRouter(prefix="/api", tags=["data"])
settings = get_settings()
SEV = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


@router.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    try:
        provider, model = ai_extractor.resolve_provider(settings)
    except ai_extractor.ExtractionError as e:
        provider, model = "misconfigured", e.user_message
    return {"status": "ok" if db_ok else "degraded", "database": db_ok, "ocr_available": ocr_service.ocr_available(),
            "extraction_provider": provider, "extraction_model": model, "time": datetime.now(timezone.utc).isoformat()}


@router.get("/settings")
def get_app_settings():
    try:
        provider, model = ai_extractor.resolve_provider(settings)
        error = None
    except ai_extractor.ExtractionError as e:
        provider, model, error = "misconfigured", "", e.user_message
    return {
        "extraction": {"provider": provider, "model": model, "configured_keys": {
            "anthropic": bool(settings.anthropic_api_key), "openai": bool(settings.openai_api_key), "gemini": bool(settings.gemini_api_key)},
            "error": error, "max_retries": settings.llm_max_retries, "timeout_s": settings.llm_timeout_s},
        "ocr": {"engine": "RapidOCR (ONNX)", "available": ocr_service.ocr_available(), "min_chars_per_page": settings.ocr_min_chars_per_page,
                "low_confidence_threshold": settings.ocr_low_confidence},
        "policy": {"tolerance_pct": str(settings.tolerance_pct), "tolerance_abs": str(settings.tolerance_abs),
                   "rounding_tolerance": str(settings.rounding_tolerance), "max_invoice_age_days": settings.max_invoice_age_days},
        "limits": {"max_upload_mb": settings.max_upload_mb, "max_pages": settings.max_pages},
        "buyer": {"name": settings.buyer_name, "tax_id": settings.buyer_tax_id},
        "demo_user": settings.demo_reviewer,
        "auth_note": "Demo mode: no authentication. A single demo reviewer identity is used and recorded in the audit trail. Not production security.",
    }


# ------------------------------------------------------------------ vendors
@router.get("/vendors")
def list_vendors(search: str | None = None, status: str | None = None, db: Session = Depends(get_db)):
    q = select(Vendor).order_by(Vendor.vendor_id)
    if status:
        q = q.where(Vendor.approval_status == status)
    if search:
        like = f"%{search}%"
        q = q.where(or_(Vendor.legal_name.ilike(like), Vendor.tax_id.ilike(like), Vendor.vendor_id.ilike(like)))
    po_counts = dict(db.execute(select(PurchaseOrder.vendor_id, func.count()).group_by(PurchaseOrder.vendor_id)).all())
    inv_counts = dict(db.execute(select(Invoice.vendor_id, func.count()).where(Invoice.vendor_id.is_not(None)).group_by(Invoice.vendor_id)).all())
    return {"items": [ser.vendor_row(v, po_counts.get(v.id, 0), inv_counts.get(v.id, 0)) for v in db.scalars(q)]}


@router.get("/vendors/{vendor_id}")
def get_vendor(vendor_id: int, db: Session = Depends(get_db)):
    v = db.get(Vendor, vendor_id)
    if not v:
        raise HTTPException(404, "Vendor not found.")
    totals = ser.po_totals(db)
    pos = list(db.scalars(select(PurchaseOrder).where(PurchaseOrder.vendor_id == v.id).order_by(PurchaseOrder.po_number)))
    invs = list(db.scalars(select(Invoice).where(Invoice.vendor_id == v.id).options(selectinload(Invoice.runs)).order_by(Invoice.created_at.desc())))
    return {**ser.vendor_row(v, len(pos), len(invs)), "purchase_order_list": [ser.po_row(p, totals.get(p.id, Decimal(0))) for p in pos],
            "invoice_list": [ser.invoice_row(i) for i in invs]}


# ------------------------------------------------------------------ purchase orders
@router.get("/purchase-orders")
def list_pos(search: str | None = None, status: str | None = None, vendor_id: int | None = None, db: Session = Depends(get_db)):
    q = select(PurchaseOrder).options(selectinload(PurchaseOrder.vendor)).order_by(PurchaseOrder.po_number)
    if vendor_id:
        q = q.where(PurchaseOrder.vendor_id == vendor_id)
    if search:
        like = f"%{search}%"
        q = q.join(Vendor, Vendor.id == PurchaseOrder.vendor_id).where(or_(PurchaseOrder.po_number.ilike(like), Vendor.legal_name.ilike(like)))
    totals = ser.po_totals(db)
    counts = dict(db.execute(select(Invoice.po_id, func.count()).where(Invoice.po_id.is_not(None)).group_by(Invoice.po_id)).all())
    items = []
    for po in db.scalars(q):
        row = ser.po_row(po, totals.get(po.id, Decimal(0)), counts.get(po.id, 0))
        if status and row["status"] != status:
            continue
        items.append(row)
    return {"items": items}


@router.get("/purchase-orders/{po_id}")
def get_po(po_id: int, db: Session = Depends(get_db)):
    po = db.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(404, "Purchase order not found.")
    bal = po_matcher.po_balance(db, po)
    invs = list(db.scalars(select(Invoice).where(Invoice.po_id == po.id).options(selectinload(Invoice.runs)).order_by(Invoice.created_at)))
    prior = po_matcher._prior_qty(db, po, None)
    return {
        **ser.po_row(po, bal["approved_total"], len(invs)),
        "lines": [{"id": l.id, "line_no": l.line_no, "item_description": l.item_description, "sku": l.sku, "quantity": ser.s(l.quantity),
                   "unit_price": ser.s(l.unit_price), "tax_rate": ser.s(l.tax_rate), "authorized_amount": ser.s(l.authorized_amount),
                   "quantity_invoiced": ser.s(prior.get(l.id, Decimal(0))), "quantity_remaining": ser.s(l.quantity - prior.get(l.id, Decimal(0)))} for l in po.lines],
        "invoices": [ser.invoice_row(i) for i in invs], "balance": {"authorized_total": ser.s(bal["authorized_total"]),
                                                                    "approved_total": ser.s(bal["approved_total"]),
                                                                    "remaining": ser.s(bal["remaining_before"]),
                                                                    "cached_remaining": ser.s(po.remaining_balance),
                                                                    "reconciled": po.remaining_balance == bal["remaining_before"]},
    }


# ------------------------------------------------------------------ reviews
@router.get("/reviews")
def review_queue(include_resolved: bool = False, db: Session = Depends(get_db)):
    q = select(Invoice).options(selectinload(Invoice.runs)).where(Invoice.source == "UPLOAD")
    if include_resolved:
        q = q.where(or_(Invoice.final_decision == "NEEDS_REVIEW", Invoice.decision_source == "MANUAL"))
    else:
        q = q.where(Invoice.final_decision == "NEEDS_REVIEW")
    rows = []
    for inv in db.scalars(q):
        d = ser.invoice_row(inv)
        detail = inv.decision_detail or {}
        d["reason"] = inv.decision_reason
        d["flagged_rules"] = detail.get("flagged_rules", [])
        d["recommended_next_action"] = detail.get("recommended_next_action")
        rows.append(d)
    rows.sort(key=lambda r: (SEV.get(r["severity"], 9), r["created_at"] or ""))
    return {"items": rows, "total": len(rows)}


# ------------------------------------------------------------------ audit
@router.get("/audit")
def audit_log(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), invoice_id: int | None = None,
              event_type: str | None = None, db: Session = Depends(get_db)):
    q = select(AuditEvent, Invoice.invoice_number).outerjoin(Invoice, Invoice.id == AuditEvent.invoice_id)
    if invoice_id:
        q = q.where(AuditEvent.invoice_id == invoice_id)
    if event_type:
        q = q.where(AuditEvent.event_type == event_type)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.execute(q.order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    types = [t for (t,) in db.execute(select(AuditEvent.event_type).distinct().order_by(AuditEvent.event_type)).all()]
    return {"items": [ser.audit_row(a, no) for a, no in rows], "total": total, "page": page, "page_size": page_size, "event_types": types}


# ------------------------------------------------------------------ dashboard
@router.get("/dashboard/metrics")
def dashboard_metrics(db: Session = Depends(get_db)):
    invs = list(db.scalars(select(Invoice).where(Invoice.source == "UPLOAD")))
    decided = [i for i in invs if i.final_decision in ("APPROVED", "NEEDS_REVIEW", "REJECTED")]
    c = Counter(i.final_decision for i in invs)
    auto_approved = sum(1 for i in decided if i.final_decision == "APPROVED" and i.decision_source == "AUTO")
    durations = [r.execution_duration for r in db.scalars(select(ProcessingRun).where(ProcessingRun.processing_status == "COMPLETED", ProcessingRun.kind == "FULL"))
                 if r.execution_duration is not None]
    value: dict[str, Decimal] = defaultdict(Decimal)
    for i in decided:
        if i.total_amount is not None and i.currency:
            value[i.currency] += i.total_amount
    approved_value: dict[str, Decimal] = defaultdict(Decimal)
    for i in decided:
        if i.final_decision == "APPROVED" and i.total_amount is not None and i.currency:
            approved_value[i.currency] += i.total_amount
    open_reviews = sum(1 for i in invs if i.final_decision == "NEEDS_REVIEW")
    return {
        "total_processed": len(decided), "approved": c["APPROVED"], "needs_review": c["NEEDS_REVIEW"], "rejected": c["REJECTED"],
        "processing_errors": c["PROCESSING_ERROR"], "in_progress": sum(1 for i in invs if i.processing_status in ("UPLOADED", "PROCESSING")),
        "auto_approval_rate": round(100 * auto_approved / len(decided), 1) if decided else None,
        "avg_processing_seconds": round(sum(durations) / len(durations), 2) if durations else None,
        "total_value_by_currency": {k: str(v) for k, v in value.items()}, "approved_value_by_currency": {k: str(v) for k, v in approved_value.items()},
        "open_reviews": open_reviews,
        "note": "Seeded historical invoices are excluded; metrics reflect invoices processed through the pipeline.",
    }


@router.get("/dashboard/trends")
def dashboard_trends(days: int = Query(14, ge=1, le=120), db: Session = Depends(get_db)):
    invs = list(db.scalars(select(Invoice).where(Invoice.source == "UPLOAD", Invoice.final_decision.is_not(None))))
    today = datetime.now(timezone.utc).date()
    daily = {(today - timedelta(days=i)).isoformat(): {"date": (today - timedelta(days=i)).isoformat(), "APPROVED": 0, "NEEDS_REVIEW": 0, "REJECTED": 0, "PROCESSING_ERROR": 0}
             for i in range(days - 1, -1, -1)}
    monthly: dict[str, dict] = {}
    vendors: dict[str, dict] = {}
    for i in invs:
        d = (i.decided_at or i.created_at).date().isoformat()
        if d in daily:
            daily[d][i.final_decision] += 1
        m = d[:7]
        mm = monthly.setdefault(m, {"month": m, "count": 0, "approved": 0, "value_inr": Decimal(0)})
        mm["count"] += 1
        if i.final_decision == "APPROVED":
            mm["approved"] += 1
        if i.currency == "INR" and i.total_amount is not None and i.final_decision != "PROCESSING_ERROR":
            mm["value_inr"] += i.total_amount
        name = i.vendor.legal_name if i.vendor else (i.vendor_name_raw or "Unknown")
        vv = vendors.setdefault(name, {"vendor": name, "count": 0, "approved": 0, "review": 0, "rejected": 0})
        vv["count"] += 1
        key = {"APPROVED": "approved", "NEEDS_REVIEW": "review", "REJECTED": "rejected"}.get(i.final_decision)
        if key:
            vv[key] += 1
    return {
        "daily": list(daily.values()),
        "monthly": [{**m, "value_inr": str(m["value_inr"])} for m in sorted(monthly.values(), key=lambda x: x["month"])],
        "vendors": sorted(vendors.values(), key=lambda v: -v["count"])[:8],
        "distribution": [{"name": "Approved", "value": sum(1 for i in invs if i.final_decision == "APPROVED")},
                         {"name": "Needs review", "value": sum(1 for i in invs if i.final_decision == "NEEDS_REVIEW")},
                         {"name": "Rejected", "value": sum(1 for i in invs if i.final_decision == "REJECTED")},
                         {"name": "Processing error", "value": sum(1 for i in invs if i.final_decision == "PROCESSING_ERROR")}],
    }


# ------------------------------------------------------------------ samples + admin (demo helpers)
def _manifest() -> dict:
    p = settings.sample_dir / "test_manifest.json"
    if not p.exists():
        return {"invoices": []}
    return json.loads(p.read_text(encoding="utf-8"))


@router.get("/samples")
def list_samples():
    m = _manifest()
    return {"generated_on": m.get("generated_on"), "items": [
        {"file": i["file"].split("/")[-1], "title": i["title"], "run_order": i["run_order"], "depends_on": i.get("depends_on"),
         "vendor": i["vendor"], "invoice_number": i["invoice_number"], "po_number": i["po_number"], "total": i["total"], "currency": i["currency"],
         "scanned": i["scanned"], "expected": i["expected"]} for i in sorted(m["invoices"], key=lambda x: x["run_order"])]}


@router.post("/samples/{filename}/load", status_code=201)
def load_sample(filename: str, db: Session = Depends(get_db)):
    """Copy a bundled sample PDF into the upload store and create an invoice (the pipeline then treats it like any upload)."""
    allowed = {i["file"].split("/")[-1] for i in _manifest()["invoices"]}
    if filename not in allowed:
        raise HTTPException(404, "Unknown sample file.")
    src = settings.sample_dir / "invoices" / filename
    if not src.exists():
        raise HTTPException(404, "Sample file is missing on the server. Run scripts/generate_sample_data.py.")
    dest = settings.upload_dir / f"{uuid.uuid4().hex}.pdf"
    shutil.copyfile(src, dest)
    inv = create_invoice_from_file(db, dest, filename)
    return ser.invoice_row(inv)


@router.post("/admin/reset")
def reset_demo(db: Session = Depends(get_db)):
    """Wipe all invoices/runs/audit and reload vendors, POs and PO history (demo reset)."""
    active = db.scalar(select(func.count()).select_from(ProcessingRun).where(ProcessingRun.processing_status.in_(["QUEUED", "RUNNING"])))
    if active:
        raise HTTPException(409, "Processing is in progress. Wait for it to finish before resetting.")
    counts = seeder.reset_database(db)
    return {"message": "Demo data reset.", "seeded": counts}
