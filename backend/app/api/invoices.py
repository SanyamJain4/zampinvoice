import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api import serializers as ser
from app.core.config import get_settings
from app.database.session import get_db
from app.models.models import Invoice
from app.schemas.requests import CorrectionRequest, ProcessRequest, ReviewRequest
from app.services import pdf_processor, workflow_service as wf

router = APIRouter(prefix="/api/invoices", tags=["invoices"])
settings = get_settings()

SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, None: 4, "NONE": 4}


def _load(db: Session, invoice_id: int) -> Invoice:
    inv = db.scalar(
        select(Invoice).where(Invoice.id == invoice_id)
        .options(selectinload(Invoice.runs), selectinload(Invoice.lines), selectinload(Invoice.validations))
    )
    if not inv:
        raise HTTPException(404, "Invoice not found.")
    return inv


def create_invoice_from_file(db: Session, path: Path, filename: str) -> Invoice:
    inv = Invoice(original_file_path=str(path), original_filename=pdf_processor.safe_filename(filename), source="UPLOAD",
                  processing_status="UPLOADED")
    db.add(inv)
    db.flush()
    wf.audit(db, "INVOICE_UPLOADED", inv.id, None, settings.demo_reviewer, new={"filename": inv.original_filename, "size_bytes": path.stat().st_size})
    db.commit()
    return inv


@router.post("/upload", status_code=201)
def upload_invoice(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Store a PDF safely (random server-side name, size + signature checks). Processing is a separate call."""
    max_bytes = settings.max_upload_mb * 1024 * 1024
    dest = settings.upload_dir / f"{uuid.uuid4().hex}.pdf"
    size = 0
    try:
        with open(dest, "wb") as fh:
            while chunk := file.file.read(1 << 20):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(413, f"The file is larger than the {settings.max_upload_mb} MB limit.")
                fh.write(chunk)
        if size == 0:
            raise HTTPException(422, "The uploaded file is empty.")
        with open(dest, "rb") as fh:
            if b"%PDF-" not in fh.read(1024):
                raise HTTPException(415, "Only PDF documents are accepted (this file has no PDF signature).")
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    inv = create_invoice_from_file(db, dest, file.filename or "invoice.pdf")
    return ser.invoice_row(_load(db, inv.id))


@router.post("/{invoice_id}/process")
def process_invoice(invoice_id: int, body: ProcessRequest | None = None, db: Session = Depends(get_db)):
    """Start a processing run. Idempotent: an in-flight or already-approved invoice returns its existing run."""
    body = body or ProcessRequest()
    inv = _load(db, invoice_id)
    last = ser.latest_run(inv)
    if inv.processing_status == "PROCESSING" and last:
        return {"run_id": last.run_id, "already_processed": False, "already_running": True, "invoice_id": inv.id}
    if inv.final_decision == "APPROVED" and last:
        return {"run_id": last.run_id, "already_processed": True, "invoice_id": inv.id,
                "message": "This invoice is already approved; re-processing is blocked so PO balance is never consumed twice."}
    if inv.final_decision in ("NEEDS_REVIEW", "REJECTED") and not body.force and last:
        return {"run_id": last.run_id, "already_processed": True, "invoice_id": inv.id,
                "message": "This invoice was already processed. Pass force=true to run it again."}
    if inv.source == "HISTORY" or not inv.original_file_path:
        raise HTTPException(409, "Historical records have no PDF and cannot be processed.")
    retry = inv.final_decision is not None
    if retry:
        wf.audit(db, "PROCESSING_RETRIED", inv.id, None, body.actor, previous={"decision": inv.final_decision}, reason="Processing re-run requested")
    inv.final_decision = None if inv.final_decision == "PROCESSING_ERROR" else inv.final_decision
    run = wf.create_run(db, inv, "FULL", body.actor)
    wf.submit_run(run.run_id)
    return {"run_id": run.run_id, "already_processed": False, "invoice_id": inv.id}


@router.get("")
def list_invoices(
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200), decision: str | None = None, status: str | None = None,
    search: str | None = None, vendor_id: int | None = None, po_id: int | None = None, include_history: bool = False,
    db: Session = Depends(get_db),
):
    q = select(Invoice).options(selectinload(Invoice.runs))
    if not include_history:
        q = q.where(Invoice.source == "UPLOAD")
    if decision:
        q = q.where(Invoice.final_decision == decision)
    if status:
        q = q.where(Invoice.processing_status == status)
    if vendor_id:
        q = q.where(Invoice.vendor_id == vendor_id)
    if po_id:
        q = q.where(Invoice.po_id == po_id)
    if search:
        like = f"%{search.strip()}%"
        q = q.where(or_(Invoice.invoice_number.ilike(like), Invoice.vendor_name_raw.ilike(like), Invoice.po_number_raw.ilike(like),
                        Invoice.original_filename.ilike(like)))
    total = db.scalar(select(func.count()).select_from(q.order_by(None).subquery()))
    rows = list(db.scalars(q.order_by(Invoice.created_at.desc(), Invoice.id.desc()).offset((page - 1) * page_size).limit(page_size)))
    return {"items": [ser.invoice_row(i) for i in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/{invoice_id}")
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    return ser.invoice_detail(db, _load(db, invoice_id))


@router.get("/{invoice_id}/file")
def get_file(invoice_id: int, db: Session = Depends(get_db)):
    inv = _load(db, invoice_id)
    if not inv.original_file_path or not Path(inv.original_file_path).exists():
        raise HTTPException(404, "The original PDF is not available.")
    return FileResponse(inv.original_file_path, media_type="application/pdf", filename=inv.original_filename,
                        content_disposition_type="inline")


@router.get("/{invoice_id}/pages/{page}.png")
def get_page_image(invoice_id: int, page: int, zoom: float = Query(1.6, ge=0.5, le=4.0), db: Session = Depends(get_db)):
    inv = _load(db, invoice_id)
    if not inv.original_file_path or not Path(inv.original_file_path).exists():
        raise HTTPException(404, "The original PDF is not available.")
    try:
        png = pdf_processor.render_page_png(Path(inv.original_file_path), page, zoom)
    except pdf_processor.PdfError as e:
        raise HTTPException(404, e.user_message) from None
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


@router.patch("/{invoice_id}/extraction")
def correct_extraction(invoice_id: int, body: CorrectionRequest, db: Session = Depends(get_db)):
    inv = _load(db, invoice_id)
    try:
        run = wf.apply_corrections(db, inv, body.corrections, body.reviewer, body.reason)
    except wf.ReviewError as e:
        raise HTTPException(e.status_code, e.message) from None
    wf.submit_run(run.run_id)
    return {"run_id": run.run_id, "invoice_id": inv.id, "message": "Corrections saved; validation is re-running."}


@router.post("/{invoice_id}/review")
def review_invoice(invoice_id: int, body: ReviewRequest, db: Session = Depends(get_db)):
    try:
        wf.manual_review(db, invoice_id, body.action, body.reviewer, body.justification)
    except wf.ReviewError as e:
        raise HTTPException(e.status_code, detail={"message": e.message, "blocking_controls": e.blocking}) from None
    return ser.invoice_detail(db, _load(db, invoice_id))
