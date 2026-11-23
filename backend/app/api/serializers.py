"""Explicit serializers (money is always a string: Decimal never passes through float)."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.models import AuditEvent, Invoice, ProcessingRun, PurchaseOrder, Vendor
from app.services import po_matcher
from app.services.decision_engine import NON_BYPASSABLE


def s(x):
    return None if x is None else str(x)


def iso(dt):
    return dt.isoformat() if dt else None


def latest_run(inv: Invoice) -> ProcessingRun | None:
    return inv.runs[-1] if inv.runs else None


def invoice_row(inv: Invoice) -> dict:
    run = latest_run(inv)
    detail = inv.decision_detail or {}
    return {
        "id": inv.id, "invoice_number": inv.invoice_number, "filename": inv.original_filename,
        "vendor_id": inv.vendor_id, "vendor_name": inv.vendor.legal_name if inv.vendor else inv.vendor_name_raw,
        "vendor_verified": inv.vendor is not None,
        "po_id": inv.po_id, "po_number": inv.po.po_number if inv.po else inv.po_number_raw,
        "invoice_date": iso(inv.invoice_date), "currency": inv.currency, "total_amount": s(inv.total_amount),
        "processing_status": inv.processing_status, "final_decision": inv.final_decision, "decision_reason": inv.decision_reason,
        "decision_source": inv.decision_source, "review_state": inv.review_state, "severity": detail.get("severity"),
        "source": inv.source, "created_at": iso(inv.created_at), "decided_at": iso(inv.decided_at),
        "duration_s": run.execution_duration if run else None, "run_id": run.run_id if run else None,
        "duplicate_of_id": inv.duplicate_of_id, "page_count": inv.page_count,
    }


def stage_row(ev, include_data: bool = True) -> dict:
    d = {
        "key": ev.stage_key, "name": ev.stage_name, "order": ev.order, "status": ev.status, "started_at": iso(ev.started_at),
        "completed_at": iso(ev.completed_at), "duration_ms": ev.duration_ms, "warnings": ev.warnings or [], "error": ev.error,
    }
    if include_data:
        d["data"] = ev.data
    return d


def run_row(run: ProcessingRun, include_stages: bool = True, include_data: bool = True) -> dict:
    d = {
        "run_id": run.run_id, "invoice_id": run.invoice_id, "filename": run.filename, "kind": run.kind, "status": run.processing_status,
        "current_stage": run.current_stage, "started_at": iso(run.started_at), "completed_at": iso(run.completed_at),
        "duration_s": run.execution_duration, "error_message": run.error_message, "final_decision": run.final_decision,
    }
    if include_stages:
        d["stages"] = [stage_row(e, include_data) for e in run.stages]
    return d


def po_totals(db: Session) -> dict[int, Decimal]:
    out: dict[int, Decimal] = {}
    for inv in db.scalars(select(Invoice).where(Invoice.final_decision == "APPROVED", Invoice.po_id.is_not(None))):
        out[inv.po_id] = out.get(inv.po_id, Decimal(0)) + (inv.total_amount or Decimal(0))
    return out


def po_row(po: PurchaseOrder, invoiced: Decimal, n_invoices: int = 0) -> dict:
    return {
        "id": po.id, "po_number": po.po_number, "vendor_id": po.vendor_id, "vendor_name": po.vendor.legal_name, "currency": po.currency,
        "issue_date": iso(po.issue_date), "subtotal": s(po.subtotal), "tax_amount": s(po.tax_amount), "authorized_total": s(po.authorized_total),
        "invoiced_amount": s(invoiced), "remaining_balance": s(po.authorized_total - invoiced), "status": po.status,
        "description": po.description, "linked_invoices": n_invoices,
    }


def vendor_row(v: Vendor, n_pos: int = 0, n_inv: int = 0) -> dict:
    return {
        "id": v.id, "vendor_id": v.vendor_id, "legal_name": v.legal_name, "aliases": v.aliases or [], "tax_id": v.tax_id,
        "country": v.country, "approval_status": v.approval_status, "created_at": iso(v.created_at),
        "purchase_orders": n_pos, "invoices": n_inv,
    }


def audit_row(a: AuditEvent, inv_no: str | None = None) -> dict:
    return {
        "id": a.id, "invoice_id": a.invoice_id, "invoice_number": inv_no, "run_id": a.run_id, "event_type": a.event_type, "actor": a.actor,
        "timestamp": iso(a.timestamp), "previous_value": a.previous_value, "new_value": a.new_value, "reason": a.reason,
    }


def invoice_detail(db: Session, inv: Invoice) -> dict:
    base = invoice_row(inv)
    detail = inv.decision_detail or {}
    po = inv.po
    po_info = None
    if po:
        bal = po_matcher.po_balance(db, po, None)
        po_info = {
            **po_row(po, bal["approved_total"]),
            "lines": [{"id": l.id, "line_no": l.line_no, "item_description": l.item_description, "sku": l.sku, "quantity": s(l.quantity),
                       "unit_price": s(l.unit_price), "tax_rate": s(l.tax_rate), "authorized_amount": s(l.authorized_amount)} for l in po.lines],
            "approved_invoices": bal["approved_invoices"],
        }
    audit = list(db.scalars(select(AuditEvent).where(AuditEvent.invoice_id == inv.id).order_by(AuditEvent.timestamp, AuditEvent.id)))
    vals = [{
        "rule_id": v.rule_id, "rule_name": v.rule_name, "severity": v.severity, "status": v.status, "expected": v.expected_value,
        "observed": v.actual_value, "explanation": v.explanation, "hard_block": v.hard_block, "details": v.details,
    } for v in inv.validations]
    blockers = [v for v in vals if v["status"] in ("FAIL", "REVIEW") and (v["rule_id"] in NON_BYPASSABLE or (v["hard_block"] and v["status"] == "FAIL"))]
    return {
        **base,
        "extraction": inv.extraction_data, "extraction_method": inv.extraction_method, "ocr_confidence": inv.ocr_confidence,
        "extracted_text": inv.extracted_text, "corrections": inv.corrections or [], "file_hash": inv.file_hash,
        "due_date": iso(inv.due_date), "subtotal": s(inv.subtotal), "tax_amount": s(inv.tax_amount),
        "lines": [{"line_no": l.line_no, "description": l.description, "sku": l.sku, "quantity": s(l.quantity), "unit_price": s(l.unit_price),
                   "tax_rate": s(l.tax_rate), "line_total": s(l.line_total), "matched_po_line_id": l.matched_po_line_id} for l in inv.lines],
        "decision": detail, "validations": vals, "approval_blockers": blockers,
        "can_approve_manually": inv.final_decision == "NEEDS_REVIEW" and not blockers,
        "vendor_match": detail.get("vendor"), "po_match": detail.get("po"), "duplicate": detail.get("duplicate"),
        "line_matching": detail.get("line_matching"), "po": po_info,
        "runs": [run_row(r, include_stages=True, include_data=False) for r in inv.runs],
        "audit": [audit_row(a, inv.invoice_number) for a in audit], "has_file": bool(inv.original_file_path) and inv.source != "HISTORY",
    }
