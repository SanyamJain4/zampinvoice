"""Workflow behaviour: idempotency, duplicates, partial billing, PO balance safety under concurrency, error handling, persistence."""
import threading
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.database.session import SessionLocal
from app.models.models import AuditEvent, Invoice, PurchaseOrder, ValidationResult
from app.services import ai_extractor, workflow_service
from tests.conftest import SAMPLE_DIR, gen, process_id, process_path, rule, wait_run

D = Decimal
INV = SAMPLE_DIR / "invoices"


def make_pdf(tmp_path: Path, name: str, vendor_id: str, inv_no: str | None, po: str, lines, days_ago: int = 3, currency: str = "INR", layout: str = "modern") -> Path:
    spec = gen.Inv(name, layout, vendor_id, inv_no, po, lines, days_ago=days_ago, currency=currency)
    vendor = next(v for v in gen.VENDORS if v[0] == vendor_id)
    path = tmp_path / name
    gen.render_pdf(spec, vendor, path, date.today())
    return path


def po_state(client, po_number: str) -> dict:
    items = client.get("/api/purchase-orders", params={"search": po_number}).json()["items"]
    return next(i for i in items if i["po_number"] == po_number)


# ---------------------------------------------------------------- duplicates + idempotency
def test_processing_is_idempotent_and_duplicates_never_consume_balance_twice(fresh):
    first = process_path(fresh, INV / "01_valid_apex.pdf")
    assert first["final_decision"] == "APPROVED"
    assert po_state(fresh, "PO-205")["invoiced_amount"] == "59000.00"

    # same invoice, processed again -> same run, no new allocation
    again = fresh.post(f"/api/invoices/{first['id']}/process", json={}).json()
    assert again["already_processed"] is True and again["run_id"] == first["run_id"]
    assert fresh.post(f"/api/invoices/{first['id']}/process", json={"force": True}).json()["already_processed"] is True  # approved invoices are locked

    # the identical file uploaded again -> confirmed duplicate (file hash), rejected, PO untouched
    dup = process_path(fresh, INV / "01_valid_apex.pdf")
    assert dup["final_decision"] == "REJECTED" and dup["duplicate_of_id"] == first["id"]
    assert rule(dup, "R08")["status"] == "FAIL" and rule(dup, "R08")["details"]["kind"] == "FILE_HASH"
    assert rule(dup, "R10")["status"] == "NOT_APPLICABLE"
    po = po_state(fresh, "PO-205")
    assert po["invoiced_amount"] == "59000.00" and po["remaining_balance"] == "0.00" and po["status"] == "FULLY_INVOICED"


def test_same_invoice_number_different_vendor_is_not_a_duplicate(fresh, tmp_path):
    a = process_path(fresh, make_pdf(tmp_path, "a.pdf", "V002", "SHARED-001", "PO-318", [gen.L("Warehousing Services per pallet-month", 10, 300)]))
    b = process_path(fresh, make_pdf(tmp_path, "b.pdf", "V004", "SHARED-001", "PO-360", [gen.L("Managed Database Instance", 1, 8000)]))
    assert a["final_decision"] == "APPROVED" and b["final_decision"] == "APPROVED"


def test_suspicious_near_duplicate_goes_to_review(fresh, tmp_path):
    process_path(fresh, make_pdf(tmp_path, "a.pdf", "V002", "BWL-5000", "PO-318", [gen.L("Warehousing Services per pallet-month", 10, 300)], days_ago=3))
    b = process_path(fresh, make_pdf(tmp_path, "b.pdf", "V002", "BWL-5001", "PO-318", [gen.L("Warehousing Services per pallet-month", 10, 300)], days_ago=3))
    assert b["final_decision"] == "NEEDS_REVIEW" and rule(b, "R08")["status"] == "REVIEW"


# ---------------------------------------------------------------- partial billing
def test_partial_billing_math_and_balance_tracking(fresh):
    assert po_state(fresh, "PO-500")["remaining_balance"] == "60000.00"  # 100,000 - 40,000 history
    inv2 = process_path(fresh, INV / "04_partial_horizon_inv2.pdf")
    r10 = rule(inv2, "R10")
    assert inv2["final_decision"] == "APPROVED"
    assert r10["details"]["remaining_before"] == "60000.00" and r10["details"]["remaining_after"] == "25000.00"
    assert po_state(fresh, "PO-500")["status"] == "PARTIALLY_INVOICED"
    inv3 = process_path(fresh, INV / "04b_partial_horizon_inv3_exceeds.pdf")
    assert inv3["final_decision"] == "NEEDS_REVIEW" and rule(inv3, "R10")["status"] == "FAIL"
    assert rule(inv3, "R10")["details"]["remaining_before"] == "25000.00"
    assert po_state(fresh, "PO-500")["remaining_balance"] == "25000.00"  # nothing allocated for the rejected one


def test_tolerance_cannot_exceed_remaining_balance(fresh):
    d = process_path(fresh, INV / "08_balance_exceeded_keystone.pdf")
    assert rule(d, "R11")["status"] == "PASS" and rule(d, "R10")["status"] == "FAIL" and d["final_decision"] == "NEEDS_REVIEW"


# ---------------------------------------------------------------- concurrency
def test_concurrent_invoices_cannot_overdraw_a_po(fresh, tmp_path):
    """PO-501 has 25,000 left (25 units). Six invoices of 10,000 race: at most two may be approved."""
    ids = []
    numbers = ["KRA-1001", "QZ/77/B", "MNO-5", "XT-9000-9", "LP.404", "HHH-31337"]  # dissimilar numbers: not "suspicious duplicates"
    for i in range(6):
        p = make_pdf(tmp_path, f"c{i}.pdf", "V011", numbers[i], "PO-501", [gen.L("Industrial Fasteners Assortment Kit", 10, 1000, 0)], days_ago=i + 1)
        with open(p, "rb") as fh:
            ids.append(fresh.post("/api/invoices/upload", files={"file": (p.name, fh, "application/pdf")}).json()["id"])
    runs = [fresh.post(f"/api/invoices/{i}/process", json={}).json()["run_id"] for i in ids]  # all start together on the worker pool
    for r in runs:
        wait_run(fresh, r)
    decisions = [fresh.get(f"/api/invoices/{i}").json()["final_decision"] for i in ids]
    assert decisions.count("APPROVED") == 2, decisions
    po = fresh.get(f"/api/purchase-orders/{po_state(fresh, 'PO-501')['id']}").json()
    assert po["balance"]["remaining"] == "5000.00" and po["balance"]["reconciled"] is True


def test_concurrent_same_invoice_number_only_one_approved(fresh, tmp_path):
    ids = []
    for i in range(3):
        p = make_pdf(tmp_path, f"d{i}.pdf", "V002", "BWL-RACE-1", "PO-318", [gen.L("Warehousing Services per pallet-month", 10 + i, 300)], days_ago=i + 1)
        with open(p, "rb") as fh:
            ids.append(fresh.post("/api/invoices/upload", files={"file": (p.name, fh, "application/pdf")}).json()["id"])
    runs = [fresh.post(f"/api/invoices/{i}/process", json={}).json()["run_id"] for i in ids]
    for r in runs:
        wait_run(fresh, r)
    decisions = sorted(fresh.get(f"/api/invoices/{i}").json()["final_decision"] for i in ids)
    assert decisions == ["APPROVED", "REJECTED", "REJECTED"], decisions


# ---------------------------------------------------------------- failures are not rejections
def test_corrupt_pdf_is_a_processing_error_not_a_rejection(fresh, tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4\n garbage garbage \n%%EOF")
    d = process_path(fresh, bad)
    assert d["final_decision"] == "PROCESSING_ERROR" and d["processing_status"] == "PROCESSING_ERROR"
    assert d["_run"]["status"] == "FAILED" and "corrupt" in d["_run"]["error_message"].lower()
    assert "Traceback" not in d["_run"]["error_message"]
    stages = {s["key"]: s["status"] for s in d["_run"]["stages"]}
    assert stages["pdf_validation"] == "FAILED" and stages["decision"] == "SKIPPED"
    assert fresh.get("/api/dashboard/metrics").json()["processing_errors"] == 1
    assert fresh.get("/api/dashboard/metrics").json()["rejected"] == 0


def test_llm_outage_is_a_processing_error_and_not_replaced_by_fake_data(fresh, monkeypatch):
    def boom(*a, **k):
        raise ai_extractor.ExtractionError("AI extraction failed after 3 attempts (HTTP 503). The invoice was not processed; please retry.", "AI_UNAVAILABLE")

    monkeypatch.setattr(workflow_service.ai_extractor, "extract_invoice", boom)
    d = process_path(fresh, INV / "01_valid_apex.pdf")
    assert d["final_decision"] == "PROCESSING_ERROR" and d["extraction"] is None
    monkeypatch.undo()
    retry = process_id(fresh, d["id"])  # retry works once the service is back
    assert retry["final_decision"] == "APPROVED"


def test_hallucinated_extraction_is_caught_by_grounding_check(fresh, monkeypatch):
    real = ai_extractor.extract_invoice

    def hallucinate(pages, settings, **k):
        res = real(pages, settings)
        res.extracted.invoice_number = "INV-FAKE-999"
        return res

    monkeypatch.setattr(workflow_service.ai_extractor, "extract_invoice", hallucinate)
    d = process_path(fresh, INV / "01_valid_apex.pdf")
    assert d["final_decision"] == "NEEDS_REVIEW" and rule(d, "R15")["status"] == "REVIEW"
    assert "invoice number" in rule(d, "R15")["observed"]


def test_prompt_injection_cannot_change_the_decision(fresh):
    d = process_path(fresh, INV / "13_prompt_injection_apex.pdf")
    assert d["final_decision"] == "NEEDS_REVIEW"
    assert "instructions" in rule(d, "R15")["observed"].lower()
    assert any("instructions" in w.lower() for w in d["_run"]["stages"][1]["warnings"])


# ---------------------------------------------------------------- explainability + persistence
def test_every_decision_has_reasons_rules_and_next_action(fresh):
    d = process_path(fresh, INV / "03_amount_mismatch_delta.pdf")
    dec = d["decision"]
    assert dec["main_reason"] and dec["detailed_reasons"] and dec["recommended_next_action"] and dec["requires_manual_intervention"] is True
    assert len(d["validations"]) == 16
    r11 = rule(d, "R11")
    assert r11["details"]["variance_pct"] == "10.00" and r11["details"]["expected_total"] == "59000.00" and r11["details"]["invoice_total"] == "64900.00"
    assert "|64,900.00 − 59,000.00| ÷ 59,000.00 × 100 = 10.00%" in r11["observed"]


def test_stage_timeline_is_persisted_with_timestamps_and_data(fresh):
    d = process_path(fresh, INV / "01_valid_apex.pdf")
    stages = d["_run"]["stages"]
    assert [s["key"] for s in stages] == ["pdf_validation", "text_extraction", "ai_extraction", "invoice_validation", "vendor_verification",
                                          "po_matching", "duplicate_detection", "financial_reconciliation", "decision"]
    for s in stages:
        assert s["status"] in ("COMPLETED", "WARNING") and s["started_at"] and s["completed_at"] and s["duration_ms"] is not None and s["data"]
    assert d["_run"]["status"] == "COMPLETED" and d["_run"]["duration_s"] > 0
    assert stages[2]["data"]["extracted"]["invoice_number"] == "APX/2026/1187"


def test_database_persistence_and_audit_trail(fresh):
    d = process_path(fresh, INV / "01_valid_apex.pdf")
    with SessionLocal() as db:  # a brand new session sees everything
        inv = db.get(Invoice, d["id"])
        assert inv.final_decision == "APPROVED" and inv.total_amount == D("59000.00") and inv.file_hash and len(inv.file_hash) == 64
        assert db.query(ValidationResult).filter_by(invoice_id=inv.id).count() == 16
        types = {a.event_type for a in db.query(AuditEvent).filter_by(invoice_id=inv.id)}
        assert {"INVOICE_UPLOADED", "PROCESSING_STARTED", "TEXT_EXTRACTED", "AI_EXTRACTION_COMPLETED", "VENDOR_MATCHED", "PO_MATCHED",
                "VALIDATION_COMPLETED", "DECISION_GENERATED"} <= types
        po = db.query(PurchaseOrder).filter_by(po_number="PO-205").one()
        assert po.status == "FULLY_INVOICED" and po.remaining_balance == D("0.00")


def test_sse_stream_delivers_progress_until_done(fresh):
    fresh_id = fresh.post("/api/samples/01_valid_apex.pdf/load").json()["id"]
    run_id = fresh.post(f"/api/invoices/{fresh_id}/process", json={}).json()["run_id"]
    snapshots, done = [], False
    with fresh.stream("GET", f"/api/runs/{run_id}/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("event: done"):
                done = True
                break
    assert done
    final = fresh.get(f"/api/runs/{run_id}").json()
    assert final["status"] == "COMPLETED" and final["final_decision"] == "APPROVED"
