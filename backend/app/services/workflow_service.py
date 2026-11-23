"""Pipeline orchestration. Every stage executes real logic and is persisted as it starts/finishes.

Stage order
  1 pdf_validation  2 text_extraction  3 ai_extraction  4 invoice_validation  5 vendor_verification
  6 po_matching     7 duplicate_detection  8 financial_reconciliation  9 decision

Concurrency: the last stage re-evaluates ALL balance/duplicate dependent rules and writes the decision
inside one critical section (process lock + `BEGIN IMMEDIATE` on SQLite / row lock on PostgreSQL), so two
invoices racing for the same PO balance (or the same invoice number) can never both be approved.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from time import perf_counter

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.session import SessionLocal, is_sqlite
from app.database.types import utcnow
from app.models.models import (AuditEvent, Invoice, InvoiceLine, ProcessingRun, PurchaseOrder, StageEvent, ValidationResult)
from app.schemas.extraction import ExtractedInvoice, build_extracted
from app.services import ai_extractor, duplicate_detector, pdf_processor, po_matcher, vendor_matcher
from app.services.ai_extractor import ExtractionError
from app.services.common import norm_invoice_number
from app.services.decision_engine import blocking_controls, decide
from app.services.pdf_processor import PdfDocument, PdfError
from app.services.security import find_injection
from app.services.validation_engine import STAGE_RULES, Ctx, RuleResult, run_rules

log = logging.getLogger("invoiceiq.workflow")
settings = get_settings()

STAGES = [
    ("pdf_validation", "PDF Validation"),
    ("text_extraction", "Text Extraction"),
    ("ai_extraction", "AI Field Extraction"),
    ("invoice_validation", "Invoice Validation"),
    ("vendor_verification", "Vendor Verification"),
    ("po_matching", "Purchase Order Matching"),
    ("duplicate_detection", "Duplicate Detection"),
    ("financial_reconciliation", "Financial Reconciliation"),
    ("decision", "Decision Generation"),
]
REUSED_ON_REVALIDATION = {"pdf_validation", "text_extraction", "ai_extraction"}

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="invoiceiq-run")
_decision_lock = threading.RLock()


def json_safe(obj):
    return json.loads(json.dumps(obj, default=str))


def audit(db: Session, event_type: str, invoice_id: int | None = None, run_id: str | None = None, actor: str = "system",
          previous=None, new=None, reason: str | None = None) -> None:
    db.add(AuditEvent(invoice_id=invoice_id, run_id=run_id, event_type=event_type, actor=actor,
                      previous_value=json_safe(previous), new_value=json_safe(new), reason=reason))


class StageFailed(Exception):
    def __init__(self, message: str, code: str = "PROCESSING_ERROR"):
        super().__init__(message)
        self.user_message, self.code = message, code


@dataclass
class State:
    invoice_id: int
    run_id: str
    kind: str
    path: Path | None = None
    doc: PdfDocument | None = None
    extracted: ExtractedInvoice | None = None
    raw_text: str = ""
    ocr_confidence: float | None = None
    method: str = ""
    injection_hits: list[str] = field(default_factory=list)
    corrected_fields: set[str] = field(default_factory=set)
    vendor: vendor_matcher.VendorMatch | None = None
    po: po_matcher.POMatch | None = None
    dup: duplicate_detector.DuplicateResult | None = None
    lines: po_matcher.LineMatchResult | None = None
    balance: dict | None = None
    rules: dict[str, RuleResult] = field(default_factory=dict)


# ------------------------------------------------------------------ run creation / submission
def create_run(db: Session, invoice: Invoice, kind: str = "FULL", actor: str = "system") -> ProcessingRun:
    run = ProcessingRun(run_id=str(uuid.uuid4()), invoice_id=invoice.id, filename=invoice.original_filename,
                        kind=kind, processing_status="QUEUED", current_stage=STAGES[0][0])
    db.add(run)
    db.flush()
    for i, (key, name) in enumerate(STAGES, 1):
        ev = StageEvent(run_pk=run.id, order=i, stage_key=key, stage_name=name, status="QUEUED", warnings=[])
        if kind == "REVALIDATION" and key in REUSED_ON_REVALIDATION:
            ev.status, ev.data = "SKIPPED", {"reused": True, "note": "Reused the stored extraction (re-validation run)."}
        db.add(ev)
    invoice.processing_status = "PROCESSING"
    audit(db, "PROCESSING_STARTED" if kind == "FULL" else "REVALIDATION_STARTED", invoice.id, run.run_id, actor,
          reason=f"Run {run.run_id[:8]} queued ({kind.lower()})")
    db.commit()
    return run


def submit_run(run_id: str) -> None:
    _executor.submit(execute_run, run_id)


def recover_interrupted_runs() -> int:
    """After a crash/restart, anything still QUEUED/RUNNING can no longer complete."""
    with SessionLocal() as db:
        runs = list(db.scalars(select(ProcessingRun).where(ProcessingRun.processing_status.in_(["QUEUED", "RUNNING"]))))
        for r in runs:
            r.processing_status, r.completed_at = "FAILED", utcnow()
            r.error_message = "Processing was interrupted by a server restart. Please retry."
            for s in r.stages:
                if s.status in ("QUEUED", "RUNNING"):
                    s.status = "FAILED" if s.status == "RUNNING" else "SKIPPED"
            inv = db.get(Invoice, r.invoice_id)
            if inv and inv.processing_status == "PROCESSING":
                inv.processing_status, inv.final_decision = "PROCESSING_ERROR", "PROCESSING_ERROR"
                inv.decision_reason = r.error_message
        db.commit()
        return len(runs)


# ------------------------------------------------------------------ executor
def execute_run(run_id: str) -> None:
    t_run = perf_counter()
    with SessionLocal() as db:
        run = db.scalar(select(ProcessingRun).where(ProcessingRun.run_id == run_id))
        if not run:
            return
        invoice = db.get(Invoice, run.invoice_id)
        st = State(invoice_id=invoice.id, run_id=run_id, kind=run.kind,
                   path=Path(invoice.original_file_path) if invoice.original_file_path else None)
        run.processing_status = "RUNNING"
        db.commit()
        try:
            if run.kind == "REVALIDATION":
                st.extracted = ExtractedInvoice.model_validate(invoice.extraction_data)
                st.raw_text = invoice.extracted_text or ""
                st.ocr_confidence = invoice.ocr_confidence
                st.method = invoice.extraction_method or ""
                st.injection_hits = find_injection(st.raw_text)
                st.corrected_fields = {c["field"] for c in (invoice.corrections or [])}
            for ev in list(run.stages):
                if ev.status == "SKIPPED":
                    continue
                _run_stage(db, run, ev, st)
            run.processing_status = "COMPLETED"
            run.final_decision = db.scalar(select(Invoice.final_decision).where(Invoice.id == st.invoice_id))
        except StageFailed as e:
            _fail_run(db, run, e.user_message)
        except Exception:  # noqa: BLE001 - last line of defence; never leak internals to the UI
            log.exception("Unexpected pipeline failure for run %s", run_id)
            db.rollback()
            _fail_run(db, run, "An unexpected internal error occurred while processing this invoice. It has been logged; please retry.")
        run = db.scalar(select(ProcessingRun).where(ProcessingRun.run_id == run_id))
        run.completed_at = utcnow()
        run.execution_duration = round(perf_counter() - t_run, 3)
        db.commit()


def _fail_run(db: Session, run: ProcessingRun, message: str) -> None:
    run = db.scalar(select(ProcessingRun).where(ProcessingRun.run_id == run.run_id))
    run.processing_status, run.error_message, run.final_decision = "FAILED", message, "PROCESSING_ERROR"
    for s in run.stages:
        if s.status == "QUEUED":
            s.status = "SKIPPED"
    inv = db.get(Invoice, run.invoice_id)
    inv.processing_status, inv.final_decision, inv.decision_reason = "PROCESSING_ERROR", "PROCESSING_ERROR", message
    inv.decision_detail = {"status": "PROCESSING_ERROR", "main_reason": message, "detailed_reasons": [message],
                           "requires_manual_intervention": False,
                           "recommended_next_action": "This is a processing failure, not a business rejection. Fix the cause and retry processing."}
    inv.decision_source, inv.review_state, inv.decided_at = "AUTO", None, utcnow()
    audit(db, "PROCESSING_FAILED", inv.id, run.run_id, reason=message)
    db.commit()


def _run_stage(db: Session, run: ProcessingRun, ev: StageEvent, st: State) -> None:
    fn = STAGE_FUNCS[ev.stage_key]
    ev.status, ev.started_at = "RUNNING", utcnow()
    run.current_stage = ev.stage_key
    db.commit()
    t0 = perf_counter()
    try:
        data, warnings = fn(db, st)
    except (PdfError, ExtractionError) as e:
        db.rollback()
        _finish_stage(db, ev, t0, "FAILED", None, [], e.user_message)
        raise StageFailed(e.user_message, getattr(e, "code", "ERROR")) from None
    except StageFailed as e:
        db.rollback()
        _finish_stage(db, ev, t0, "FAILED", None, [], e.user_message)
        raise
    except Exception:  # noqa: BLE001
        log.exception("Stage %s crashed", ev.stage_key)
        db.rollback()
        msg = f"An internal error occurred during '{ev.stage_name}'."
        _finish_stage(db, ev, t0, "FAILED", None, [], msg)
        raise StageFailed(msg) from None
    _finish_stage(db, ev, t0, "WARNING" if warnings else "COMPLETED", data, warnings, None)


def _finish_stage(db: Session, ev: StageEvent, t0: float, status: str, data, warnings, error) -> None:
    ev = db.get(StageEvent, ev.id)
    ev.status, ev.data, ev.warnings, ev.error = status, json_safe(data), json_safe(warnings), error
    ev.completed_at, ev.duration_ms = utcnow(), int((perf_counter() - t0) * 1000)
    db.commit()


# ------------------------------------------------------------------ helpers
def sync_invoice_from_extraction(invoice: Invoice, ex: ExtractedInvoice) -> None:
    invoice.vendor_name_raw, invoice.po_number_raw = ex.vendor_name, ex.po_number
    invoice.invoice_number, invoice.invoice_number_norm = ex.invoice_number, norm_invoice_number(ex.invoice_number)
    invoice.invoice_date, invoice.due_date, invoice.currency = ex.invoice_date, ex.due_date, ex.currency
    invoice.subtotal, invoice.tax_amount, invoice.total_amount = ex.subtotal, ex.tax_amount, ex.grand_total
    invoice.extraction_data = json_safe(ex.model_dump(mode="json"))
    invoice.lines.clear()
    for i, l in enumerate(ex.line_items, 1):
        invoice.lines.append(InvoiceLine(line_no=i, description=l.description, sku=l.sku, quantity=l.quantity,
                                         unit_price=l.unit_price, tax_rate=l.tax_rate, line_total=l.line_total))


def _ctx(st: State, balance, vendor=None, po=None, dup=None, lines=None) -> Ctx:
    return Ctx(
        ex=st.extracted, settings=settings,
        vendor=vendor or st.vendor or vendor_matcher.VendorMatch("UNRECOGNIZED", message="Vendor not yet verified."),
        po=po or st.po or po_matcher.POMatch("NO_REFERENCE", message="PO not yet matched."),
        lines=lines or st.lines or po_matcher.LineMatchResult(),
        dup=dup or st.dup or duplicate_detector.DuplicateResult("NONE"),
        balance=balance if balance is not None else st.balance,
        raw_text=st.raw_text, ocr_confidence=st.ocr_confidence, extraction_method=st.method,
        injection_hits=st.injection_hits, corrected_fields=st.corrected_fields, today=date.today(),
    )


def _rules_payload(results: list[RuleResult]) -> list[dict]:
    return [r.to_dict() for r in results]


def _summ(results: list[RuleResult]) -> dict:
    out = {"PASS": 0, "FAIL": 0, "REVIEW": 0, "NOT_APPLICABLE": 0}
    for r in results:
        out[r.status] += 1
    return out


def _rule_warnings(results: list[RuleResult]) -> list[str]:
    return [f"{r.rule_id} {r.rule_name}: {r.observed}" for r in results if r.status in ("FAIL", "REVIEW")]


# ------------------------------------------------------------------ stages
def stage_pdf_validation(db: Session, st: State):
    inv = db.get(Invoice, st.invoice_id)
    info = pdf_processor.validate_pdf(st.path, settings)
    inv.file_hash, inv.page_count = info["sha256"], info["pages"]
    db.commit()
    return {"pages": info["pages"], "size_kb": round(info["size_bytes"] / 1024, 1), "sha256": info["sha256"],
            "encrypted": False, "filename": inv.original_filename}, []


def stage_text_extraction(db: Session, st: State):
    inv = db.get(Invoice, st.invoice_id)
    doc = pdf_processor.extract_document(st.path, settings)
    st.doc, st.raw_text, st.ocr_confidence = doc, doc.full_text, doc.ocr_confidence
    st.injection_hits = find_injection(st.raw_text)
    inv.extracted_text, inv.ocr_confidence = doc.full_text, doc.ocr_confidence
    audit(db, "TEXT_EXTRACTED", inv.id, st.run_id, new={"method": doc.method, "pages": doc.page_count, "chars": doc.total_chars})
    db.commit()
    warnings = []
    if doc.method != "TEXT":
        warnings.append(f"Scanned content detected: OCR was used (mean confidence {doc.ocr_confidence:.0%})." if doc.ocr_confidence else "OCR was used.")
        if doc.ocr_confidence is not None and doc.ocr_confidence < settings.ocr_low_confidence:
            warnings.append("OCR confidence is below the reliability threshold; extracted values will be double-checked.")
    if st.injection_hits:
        warnings.append("The document contains text that looks like instructions to an AI system. It is treated as data and ignored.")
    return {
        "method": doc.method, "pages": [{"page": p.page, "method": p.method, "chars": p.chars,
                                         "ocr_confidence": p.ocr_confidence} for p in doc.pages],
        "total_chars": doc.total_chars, "ocr_confidence": doc.ocr_confidence,
        "preview": doc.pages[0].text[:700], "injection_suspected": bool(st.injection_hits),
    }, warnings


def stage_ai_extraction(db: Session, st: State):
    inv = db.get(Invoice, st.invoice_id)
    res = ai_extractor.extract_invoice([p.lines for p in st.doc.pages], settings)
    st.extracted, st.method = res.extracted, res.method
    inv.extraction_method = res.method
    sync_invoice_from_extraction(inv, res.extracted)
    inv.corrections = []
    audit(db, "AI_EXTRACTION_COMPLETED", inv.id, st.run_id, new={"provider": res.provider, "model": res.model,
                                                               "missing": res.extracted.missing_fields})
    db.commit()
    ex = res.extracted
    return {
        "provider": res.provider, "model": res.model, "method": res.method, "attempts": res.attempts,
        "extracted": ex.model_dump(mode="json"), "missing_fields": ex.missing_fields,
    }, [*res.notes, *ex.warnings]


def stage_invoice_validation(db: Session, st: State):
    results = run_rules(_ctx(st, None), STAGE_RULES["invoice_validation"])
    for r in results:
        st.rules[r.rule_id] = r
    return {"rules": _rules_payload(results), "summary": _summ(results)}, _rule_warnings(results)


def stage_vendor_verification(db: Session, st: State):
    inv = db.get(Invoice, st.invoice_id)
    st.vendor = vendor_matcher.match_vendor(db, st.extracted)
    inv.vendor_id = st.vendor.vendor.id if st.vendor.verified else None
    audit(db, "VENDOR_MATCHED", inv.id, st.run_id, new=st.vendor.to_dict())
    db.commit()
    results = run_rules(_ctx(st, None), STAGE_RULES["vendor_verification"])
    st.rules.update({r.rule_id: r for r in results})
    return {"vendor": st.vendor.to_dict(), "rules": _rules_payload(results), "summary": _summ(results)}, _rule_warnings(results)


def stage_po_matching(db: Session, st: State):
    inv = db.get(Invoice, st.invoice_id)
    st.po = po_matcher.match_po(db, st.extracted, st.vendor, inv.id)
    st.balance = po_matcher.po_balance(db, st.po.po, inv.id) if st.po.po else None
    inv.po_id = st.po.po.id if st.po.po else None
    audit(db, "PO_MATCHED", inv.id, st.run_id, new=st.po.to_dict())
    db.commit()
    results = run_rules(_ctx(st, st.balance), STAGE_RULES["po_matching"])
    st.rules.update({r.rule_id: r for r in results})
    data = {"po": st.po.to_dict(), "rules": _rules_payload(results), "summary": _summ(results)}
    if st.balance:
        data["balance"] = json_safe(st.balance)
    return data, _rule_warnings(results)


def stage_duplicate_detection(db: Session, st: State):
    inv = db.get(Invoice, st.invoice_id)
    st.dup = duplicate_detector.detect(db, inv, st.extracted, st.vendor)
    results = run_rules(_ctx(st, st.balance), STAGE_RULES["duplicate_detection"])
    st.rules.update({r.rule_id: r for r in results})
    return {"duplicate": st.dup.to_dict(), "rules": _rules_payload(results), "summary": _summ(results)}, _rule_warnings(results)


def stage_financial_reconciliation(db: Session, st: State):
    inv = db.get(Invoice, st.invoice_id)
    st.lines = po_matcher.match_lines(db, st.extracted, st.po.po, settings, inv.id)
    results = run_rules(_ctx(st, st.balance), STAGE_RULES["financial_reconciliation"])
    st.rules.update({r.rule_id: r for r in results})
    audit(db, "VALIDATION_COMPLETED", inv.id, st.run_id, new=_summ(list(st.rules.values())))
    db.commit()
    data = {"line_matching": st.lines.to_dict(), "rules": _rules_payload(results), "summary": _summ(results)}
    if st.balance:
        data["balance"] = json_safe(st.balance)
    return data, _rule_warnings(results)


def stage_decision(db: Session, st: State):
    staged = {k: v.status for k, v in st.rules.items()}
    decision, final_rules = commit_decision(st)
    changed = [r.rule_id for r in final_rules if staged.get(r.rule_id) not in (None, r.status)]
    note = ([f"Re-evaluated under the PO lock; outcome changed for {', '.join(changed)} since the earlier stage "
             "(another invoice was processed in the meantime)."] if changed else [])
    warn = ([decision["main_reason"]] if decision["status"] != "APPROVED" else []) + note
    return {"decision": decision, "rules": _rules_payload(final_rules), "summary": decision["rules_summary"],
            "reevaluated_under_lock": True, "changed_rules": changed}, warn


STAGE_FUNCS = {
    "pdf_validation": stage_pdf_validation, "text_extraction": stage_text_extraction, "ai_extraction": stage_ai_extraction,
    "invoice_validation": stage_invoice_validation, "vendor_verification": stage_vendor_verification,
    "po_matching": stage_po_matching, "duplicate_detection": stage_duplicate_detection,
    "financial_reconciliation": stage_financial_reconciliation, "decision": stage_decision,
}


# ------------------------------------------------------------------ critical section
def _begin_exclusive(db: Session) -> None:
    if is_sqlite:
        db.execute(text("BEGIN IMMEDIATE"))


def _evaluate_fresh(db: Session, invoice: Invoice, st: State):
    """Recompute everything that depends on shared state (vendor/PO/duplicates/balance) and run ALL rules."""
    ex = st.extracted
    vendor = vendor_matcher.match_vendor(db, ex)
    po = po_matcher.match_po(db, ex, vendor, invoice.id)
    if po.po is not None:  # row lock on PostgreSQL; BEGIN IMMEDIATE already serialises SQLite
        db.execute(select(PurchaseOrder.id).where(PurchaseOrder.id == po.po.id).with_for_update())
    balance = po_matcher.po_balance(db, po.po, invoice.id) if po.po else None
    dup = duplicate_detector.detect(db, invoice, ex, vendor)
    lines = po_matcher.match_lines(db, ex, po.po, settings, invoice.id)
    ctx = _ctx(st, balance, vendor, po, dup, lines)
    rules = run_rules(ctx)
    return ctx, rules, vendor, po, dup, lines


def _persist_validations(db: Session, invoice: Invoice, run_id: str | None, rules: list[RuleResult]) -> None:
    db.execute(delete(ValidationResult).where(ValidationResult.invoice_id == invoice.id))
    for r in rules:
        db.add(ValidationResult(invoice_id=invoice.id, run_id=run_id, rule_id=r.rule_id, rule_name=r.rule_name,
                                severity=r.severity, status=r.status, expected_value=r.expected, actual_value=r.observed,
                                explanation=r.explanation, hard_block=r.hard_block, details=json_safe(r.details)))


def commit_decision(st: State):
    with _decision_lock, SessionLocal() as db:
        _begin_exclusive(db)
        invoice = db.get(Invoice, st.invoice_id)
        ctx, rules, vendor, po, dup, lines = _evaluate_fresh(db, invoice, st)
        decision = decide(rules, ctx)
        decision["line_matching"] = lines.to_dict()
        decision["vendor"] = vendor.to_dict()
        decision["po"] = po.to_dict()
        decision["duplicate"] = dup.to_dict()

        invoice.vendor_id = vendor.vendor.id if vendor.verified else None
        invoice.po_id = po.po.id if po.po else None
        invoice.final_decision, invoice.decision_reason = decision["status"], decision["main_reason"]
        invoice.decision_detail, invoice.decision_source = json_safe(decision), "AUTO"
        invoice.review_state = "OPEN" if decision["status"] == "NEEDS_REVIEW" else None
        invoice.processing_status, invoice.decided_at = "PROCESSED", utcnow()
        invoice.duplicate_of_id = dup.original.id if dup.status == "CONFIRMED" and dup.original else None
        for il in invoice.lines:
            match = next((m for m in lines.lines if m["index"] == il.line_no), None)
            il.matched_po_line_id = match["po_line_id"] if match else None
        _persist_validations(db, invoice, st.run_id, rules)
        db.flush()
        if po.po is not None:
            po_matcher.reconcile_po(db, po.po)
        audit(db, "DECISION_GENERATED", invoice.id, st.run_id, previous=None,
              new={"decision": decision["status"], "severity": decision["severity"]}, reason=decision["main_reason"])
        db.commit()
        return decision, rules


# ------------------------------------------------------------------ human-in-the-loop
class ReviewError(Exception):
    def __init__(self, message: str, status_code: int = 409, blocking: list[dict] | None = None):
        super().__init__(message)
        self.message, self.status_code, self.blocking = message, status_code, blocking or []


ALLOWED_CORRECTIONS = {"vendor_name", "vendor_tax_id", "invoice_number", "invoice_date", "due_date", "po_number",
                       "currency", "subtotal", "discount", "shipping", "tax_amount", "grand_total", "line_items"}


def apply_corrections(db: Session, invoice: Invoice, corrections: dict, reviewer: str, reason: str) -> ProcessingRun:
    if invoice.final_decision != "NEEDS_REVIEW":
        raise ReviewError("Only invoices that are waiting for review can be corrected.")
    unknown = set(corrections) - ALLOWED_CORRECTIONS
    if unknown:
        raise ReviewError(f"These fields cannot be corrected: {', '.join(sorted(unknown))}.", 422)
    if not corrections:
        raise ReviewError("No corrections were supplied.", 422)
    original = dict(invoice.extraction_data or {})
    merged = {**original, **corrections}
    try:
        new_ex = build_extracted({**merged, "warnings": [], "evidence": original.get("evidence", {})})
    except Exception:
        raise ReviewError("The corrected values are not valid (check numbers and dates).", 422) from None
    changed = []
    log_entries = list(invoice.corrections or [])
    old_ex = ExtractedInvoice.model_validate(original)
    for f in corrections:
        before, after = getattr(old_ex, f), getattr(new_ex, f)
        if json_safe(before) != json_safe(after):
            changed.append(f)
            log_entries.append({"field": f, "original": json_safe(before), "corrected": json_safe(after), "by": reviewer,
                                "at": utcnow().isoformat(), "reason": reason})
            audit(db, "DATA_CORRECTED", invoice.id, None, reviewer, previous={f: json_safe(before)}, new={f: json_safe(after)}, reason=reason)
    if not changed:
        raise ReviewError("The supplied values are identical to the current extraction.", 422)
    sync_invoice_from_extraction(invoice, new_ex)
    invoice.corrections = log_entries
    invoice.review_state = "OPEN"
    db.commit()
    return create_run(db, invoice, "REVALIDATION", reviewer)


def manual_review(db: Session, invoice_id: int, action: str, reviewer: str, justification: str) -> Invoice:
    """APPROVE / REJECT / REQUEST_CLARIFICATION. Hard controls cannot be bypassed."""
    with _decision_lock:
        _begin_exclusive(db)
        invoice = db.get(Invoice, invoice_id)
        if invoice is None:
            raise ReviewError("Invoice not found.", 404)
        if invoice.final_decision != "NEEDS_REVIEW":
            raise ReviewError(f"This invoice is {invoice.final_decision or 'not processed'}; only invoices waiting for review can be actioned.")
        prev = {"decision": invoice.final_decision, "review_state": invoice.review_state}

        if action == "REQUEST_CLARIFICATION":
            invoice.review_state = "CLARIFICATION_REQUESTED"
            audit(db, "CLARIFICATION_REQUESTED", invoice.id, None, reviewer, previous=prev,
                  new={"review_state": "CLARIFICATION_REQUESTED"}, reason=justification)
            db.commit()
            return invoice

        if action == "REJECT":
            invoice.final_decision, invoice.review_state, invoice.decision_source = "REJECTED", "RESOLVED", "MANUAL"
            invoice.decision_reason = f"Rejected by {reviewer}: {justification}"
            detail = dict(invoice.decision_detail or {})
            detail.update(status="REJECTED", main_reason=invoice.decision_reason, manual={"by": reviewer, "action": "REJECT", "justification": justification},
                          requires_manual_intervention=False, recommended_next_action="Do not pay. Inform the vendor if appropriate.")
            invoice.decision_detail, invoice.decided_at = json_safe(detail), utcnow()
            audit(db, "MANUAL_REVIEW", invoice.id, None, reviewer, previous=prev, new={"decision": "REJECTED"}, reason=justification)
            db.flush()
            if invoice.po:
                po_matcher.reconcile_po(db, invoice.po)
            db.commit()
            return invoice

        # APPROVE: re-run every control against the live state under the lock.
        st = State(invoice_id=invoice.id, run_id="manual", kind="MANUAL")
        st.extracted = ExtractedInvoice.model_validate(invoice.extraction_data)
        st.raw_text, st.ocr_confidence, st.method = invoice.extracted_text or "", invoice.ocr_confidence, invoice.extraction_method or ""
        st.injection_hits = find_injection(st.raw_text)
        st.corrected_fields = {c["field"] for c in (invoice.corrections or [])}
        ctx, rules, vendor, po, dup, lines = _evaluate_fresh(db, invoice, st)
        blockers = blocking_controls(rules)
        if blockers:
            raise ReviewError(
                "This invoice cannot be approved manually because hard financial controls are not satisfied: "
                + "; ".join(f"{b.rule_id} {b.rule_name}" for b in blockers)
                + ". Correct the data (and re-run validation) or resolve the issue upstream (PO amendment, vendor master).",
                409, [b.to_dict() for b in blockers])
        decision = decide(rules, ctx)
        po_row = po.po
        invoice.vendor_id, invoice.po_id = vendor.vendor.id, po_row.id
        invoice.final_decision, invoice.review_state, invoice.decision_source = "APPROVED", "RESOLVED", "MANUAL"
        invoice.decision_reason = f"Approved by {reviewer} after manual review: {justification}"
        decision.update(status="APPROVED", main_reason=invoice.decision_reason,
                        manual={"by": reviewer, "action": "APPROVE", "justification": justification,
                                "overridden_rules": [r.rule_id for r in rules if r.status in ("FAIL", "REVIEW")]},
                        requires_manual_intervention=False, line_matching=lines.to_dict(), vendor=vendor.to_dict(), po=po.to_dict(),
                        duplicate=dup.to_dict())
        r10 = next(r for r in rules if r.rule_id == "R10").details
        decision["allocation"] = {"po_number": po_row.po_number, "currency": po_row.currency, "invoice_total": str(ctx.ex.grand_total),
                                  "remaining_before": r10.get("remaining_before"), "remaining_after": r10.get("remaining_after")}
        decision["recommended_next_action"] = "Ready for the payment run (this system does not execute payments)."
        invoice.decision_detail, invoice.decided_at = json_safe(decision), utcnow()
        for il in invoice.lines:
            m = next((x for x in lines.lines if x["index"] == il.line_no), None)
            il.matched_po_line_id = m["po_line_id"] if m else None
        _persist_validations(db, invoice, None, rules)
        db.flush()
        po_matcher.reconcile_po(db, po_row)
        audit(db, "MANUAL_REVIEW", invoice.id, None, reviewer, previous=prev,
              new={"decision": "APPROVED", "overridden_rules": decision["manual"]["overridden_rules"]}, reason=justification)
        db.commit()
        return invoice
