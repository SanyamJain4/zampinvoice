import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api import serializers as ser
from app.database.session import SessionLocal, get_db
from app.models.models import ProcessingRun

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _run(db: Session, run_id: str) -> ProcessingRun:
    run = db.scalar(select(ProcessingRun).where(ProcessingRun.run_id == run_id).options(selectinload(ProcessingRun.stages)))
    if not run:
        raise HTTPException(404, "Run not found.")
    return run


@router.get("")
def list_runs(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200), status: str | None = None,
              invoice_id: int | None = None, db: Session = Depends(get_db)):
    q = select(ProcessingRun)
    if status:
        q = q.where(ProcessingRun.processing_status == status)
    if invoice_id:
        q = q.where(ProcessingRun.invoice_id == invoice_id)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = list(db.scalars(q.options(selectinload(ProcessingRun.stages), selectinload(ProcessingRun.invoice))
                           .order_by(ProcessingRun.started_at.desc()).offset((page - 1) * page_size).limit(page_size)))
    items = []
    for r in rows:
        d = ser.run_row(r, include_stages=True, include_data=False)
        d["invoice_number"] = r.invoice.invoice_number
        d["vendor_name"] = r.invoice.vendor.legal_name if r.invoice.vendor else r.invoice.vendor_name_raw
        d["total_amount"] = ser.s(r.invoice.total_amount)
        d["currency"] = r.invoice.currency
        items.append(d)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db)):
    return ser.run_row(_run(db, run_id))


@router.get("/{run_id}/events")
def run_events(run_id: str):
    """Server-Sent Events: a full run snapshot every time anything changes (the UI falls back to polling GET /api/runs/{id})."""

    def gen():
        last, started, last_ping = None, time.time(), time.time()
        while time.time() - started < 900:
            with SessionLocal() as db:
                run = db.scalar(select(ProcessingRun).where(ProcessingRun.run_id == run_id).options(selectinload(ProcessingRun.stages)))
                if run is None:
                    yield "event: error\ndata: {\"message\": \"Run not found\"}\n\n"
                    return
                snap = ser.run_row(run)
            payload = json.dumps(snap, default=str)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if snap["status"] in ("COMPLETED", "FAILED"):
                yield "event: done\ndata: {}\n\n"
                return
            if time.time() - last_ping > 15:
                yield ": ping\n\n"
                last_ping = time.time()
            time.sleep(0.3)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
