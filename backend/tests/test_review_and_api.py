"""Human-in-the-loop review, hard-control enforcement, and API contract tests."""
import pytest

from app.core.config import get_settings
from tests.conftest import SAMPLE_DIR, process_id, process_path, rule, wait_run

INV = SAMPLE_DIR / "invoices"


def review(client, inv_id, action, text="Verified against the PDF and PO with procurement.", reviewer="qa.reviewer@test"):
    return client.post(f"/api/invoices/{inv_id}/review", json={"action": action, "justification": text, "reviewer": reviewer})


# ---------------------------------------------------------------- correction -> revalidation -> approval
def test_missing_invoice_number_full_review_cycle(fresh):
    d = process_path(fresh, INV / "05_missing_number_cedar.pdf")
    assert d["final_decision"] == "NEEDS_REVIEW" and d["review_state"] == "OPEN"
    assert d["can_approve_manually"] is False and any(b["rule_id"] == "R01" for b in d["approval_blockers"])  # cannot approve without an invoice number
    assert review(fresh, d["id"], "APPROVE").status_code == 409

    q = fresh.get("/api/reviews").json()
    assert q["total"] == 1 and q["items"][0]["id"] == d["id"] and q["items"][0]["reason"]

    # invalid / non-whitelisted corrections are refused
    assert fresh.patch(f"/api/invoices/{d['id']}/extraction", json={"corrections": {"final_decision": "APPROVED"}, "reason": "trying something"}).status_code == 422
    assert fresh.patch(f"/api/invoices/{d['id']}/extraction", json={"corrections": {"invoice_number": "X1"}, "reason": "x"}).status_code == 422  # reason too short

    r = fresh.patch(f"/api/invoices/{d['id']}/extraction", json={"corrections": {"invoice_number": "CED-2611-077"}, "reason": "Number is on the PDF footer stamp", "reviewer": "qa.reviewer@test"})
    assert r.status_code == 200
    run = wait_run(fresh, r.json()["run_id"])
    assert run["kind"] == "REVALIDATION" and [s["status"] for s in run["stages"][:3]] == ["SKIPPED"] * 3
    d2 = fresh.get(f"/api/invoices/{d['id']}").json()
    assert d2["invoice_number"] == "CED-2611-077" and rule(d2, "R01")["status"] == "PASS" and rule(d2, "R08")["status"] == "PASS"
    # corrected data is never auto-approved: a human has to approve explicitly
    assert d2["final_decision"] == "NEEDS_REVIEW" and d2["decision"]["corrected_data"] is True and d2["can_approve_manually"] is True
    assert d2["corrections"][0]["original"] is None and d2["corrections"][0]["corrected"] == "CED-2611-077" and d2["corrections"][0]["by"] == "qa.reviewer@test"

    assert review(fresh, d["id"], "APPROVE", "too short").status_code == 422  # justification is mandatory
    ok = review(fresh, d["id"], "APPROVE")
    assert ok.status_code == 200
    d3 = ok.json()
    assert d3["final_decision"] == "APPROVED" and d3["decision_source"] == "MANUAL" and d3["review_state"] == "RESOLVED"
    types = [a["event_type"] for a in d3["audit"]]
    assert "DATA_CORRECTED" in types and "MANUAL_REVIEW" in types and "REVALIDATION_STARTED" in types
    manual = next(a for a in d3["audit"] if a["event_type"] == "MANUAL_REVIEW")
    assert manual["actor"] == "qa.reviewer@test" and manual["previous_value"]["decision"] == "NEEDS_REVIEW" and manual["new_value"]["decision"] == "APPROVED"
    po = next(p for p in fresh.get("/api/purchase-orders").json()["items"] if p["po_number"] == "PO-340")
    assert po["invoiced_amount"] == "82600.00"
    assert fresh.get("/api/reviews").json()["total"] == 0
    assert review(fresh, d["id"], "APPROVE").status_code == 409  # already resolved


def test_manual_approval_cannot_bypass_hard_financial_controls(fresh):
    process_path(fresh, INV / "04_partial_horizon_inv2.pdf")
    over = process_path(fresh, INV / "04b_partial_horizon_inv3_exceeds.pdf")  # R10 fails
    r = review(fresh, over["id"], "APPROVE")
    assert r.status_code == 409
    body = r.json()
    assert any(b["rule_id"] == "R10" for b in body["blocking_controls"]) and "hard financial controls" in body["message"]
    assert fresh.get(f"/api/invoices/{over['id']}").json()["final_decision"] == "NEEDS_REVIEW"
    po = next(p for p in fresh.get("/api/purchase-orders").json()["items"] if p["po_number"] == "PO-500")
    assert po["remaining_balance"] == "25000.00"
    # wrong vendor / currency mismatch / inactive vendor are also non-bypassable
    for f, rid in [("07_wrong_vendor_lumen.pdf", "R04"), ("09_currency_mismatch_globex.pdf", "R05"), ("11_inactive_vendor_indigo.pdf", "R02")]:
        d = process_path(fresh, INV / f)
        resp = review(fresh, d["id"], "APPROVE")
        assert resp.status_code == 409 and any(b["rule_id"] == rid for b in resp.json()["blocking_controls"]), f


def test_duplicates_and_blocked_vendors_cannot_be_reviewed_into_approval(fresh):
    d = process_path(fresh, INV / "02_duplicate_bluewave.pdf")
    assert d["final_decision"] == "REJECTED"
    assert review(fresh, d["id"], "APPROVE").status_code == 409
    b = process_path(fresh, INV / "12_blocked_vendor_jupiter.pdf")
    assert b["final_decision"] == "REJECTED" and review(fresh, b["id"], "APPROVE").status_code == 409


def test_soft_issue_can_be_approved_with_justification_and_overrides_are_audited(fresh):
    d = process_path(fresh, INV / "10_bundled_evergreen.pdf")  # R16 bundled lines -> reviewer judgement
    assert d["can_approve_manually"] is True
    out = review(fresh, d["id"], "APPROVE", "Confirmed with Evergreen: package = housekeeping + pantry + garden per PO-370.").json()
    assert out["final_decision"] == "APPROVED" and "R16" in out["decision"]["manual"]["overridden_rules"]
    assert out["decision"]["allocation"]["remaining_after"] == "0.00"


def test_reject_and_request_clarification(fresh):
    a = process_path(fresh, INV / "10_bundled_evergreen.pdf")
    c = review(fresh, a["id"], "REQUEST_CLARIFICATION", "Please send an itemised invoice split by PO line.").json()
    assert c["final_decision"] == "NEEDS_REVIEW" and c["review_state"] == "CLARIFICATION_REQUESTED"
    assert any(x["event_type"] == "CLARIFICATION_REQUESTED" for x in c["audit"])
    r = review(fresh, a["id"], "REJECT", "Vendor refused to itemise the invoice.").json()
    assert r["final_decision"] == "REJECTED" and r["decision_source"] == "MANUAL"
    po = next(p for p in fresh.get("/api/purchase-orders").json()["items"] if p["po_number"] == "PO-370")
    assert po["invoiced_amount"] == "0"  # a rejected invoice never consumes PO balance


# ---------------------------------------------------------------- API contract
def test_upload_validation(fresh, tmp_path, monkeypatch):
    r = fresh.post("/api/invoices/upload", files={"file": ("x.pdf", b"just text", "application/pdf")})
    assert r.status_code == 415 and r.json()["error"] is True and "PDF" in r.json()["message"]  # content-type lies, signature checked
    assert fresh.post("/api/invoices/upload", files={"file": ("x.pdf", b"", "application/pdf")}).status_code == 422
    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    assert fresh.post("/api/invoices/upload", files={"file": ("x.pdf", b"%PDF-1.4 abc", "application/pdf")}).status_code == 413
    monkeypatch.undo()
    r = fresh.post("/api/invoices/upload", files={"file": ("../../etc/passwd.pdf", (INV / "01_valid_apex.pdf").read_bytes(), "application/pdf")})
    assert r.status_code == 201 and "/" not in r.json()["filename"] and ".." not in r.json()["filename"]
    assert fresh.get("/api/invoices/999999").status_code == 404


def test_listing_filters_pagination_and_detail_shape(fresh):
    for f in ["01_valid_apex.pdf", "03_amount_mismatch_delta.pdf", "12_blocked_vendor_jupiter.pdf"]:
        process_path(fresh, INV / f)
    page = fresh.get("/api/invoices", params={"page_size": 2}).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    assert fresh.get("/api/invoices", params={"decision": "REJECTED"}).json()["total"] == 1
    assert fresh.get("/api/invoices", params={"search": "Delta"}).json()["total"] == 1
    assert fresh.get("/api/invoices", params={"include_history": True}).json()["total"] == 3 + 4
    inv = fresh.get("/api/invoices").json()["items"][-1]
    d = fresh.get(f"/api/invoices/{inv['id']}").json()
    for k in ("extraction", "lines", "validations", "decision", "po", "runs", "audit", "line_matching", "vendor_match"):
        assert k in d
    assert fresh.get(f"/api/invoices/{inv['id']}/file").headers["content-type"] == "application/pdf"
    png = fresh.get(f"/api/invoices/{inv['id']}/pages/1.png")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    assert fresh.get(f"/api/invoices/{inv['id']}/pages/9.png").status_code == 404


def test_master_data_endpoints(fresh):
    v = fresh.get("/api/vendors").json()["items"]
    assert len(v) >= 12 and {x["approval_status"] for x in v} == {"APPROVED", "INACTIVE", "BLOCKED"}
    assert fresh.get(f"/api/vendors/{v[0]['id']}").json()["purchase_order_list"]
    assert fresh.get("/api/vendors", params={"search": "Apex"}).json()["items"]
    pos = fresh.get("/api/purchase-orders").json()["items"]
    assert len(pos) >= 15 and {"OPEN", "PARTIALLY_INVOICED", "FULLY_INVOICED", "CLOSED"} <= {p["status"] for p in pos}
    po = fresh.get(f"/api/purchase-orders/{pos[0]['id']}").json()
    assert po["lines"] and po["balance"]["reconciled"] is True
    assert fresh.get("/api/purchase-orders/99999").status_code == 404


def test_dashboard_is_computed_from_persisted_data(fresh):
    empty = fresh.get("/api/dashboard/metrics").json()
    assert empty["total_processed"] == 0 and empty["auto_approval_rate"] is None
    for f in ["01_valid_apex.pdf", "03_amount_mismatch_delta.pdf", "12_blocked_vendor_jupiter.pdf", "15_tolerance_lumen.pdf"]:
        process_path(fresh, INV / f)
    m = fresh.get("/api/dashboard/metrics").json()
    assert (m["total_processed"], m["approved"], m["needs_review"], m["rejected"]) == (4, 2, 1, 1)
    assert m["auto_approval_rate"] == 50.0 and m["avg_processing_seconds"] > 0
    assert m["approved_value_by_currency"]["INR"] == "129505.00" and m["open_reviews"] == 1
    t = fresh.get("/api/dashboard/trends").json()
    assert sum(sum(d[k] for k in ("APPROVED", "NEEDS_REVIEW", "REJECTED")) for d in t["daily"]) == 4
    assert t["vendors"] and t["monthly"] and {x["name"] for x in t["distribution"]} >= {"Approved"}
    runs = fresh.get("/api/runs").json()
    assert runs["total"] == 4 and runs["items"][0]["stages"]


def test_audit_endpoint_and_health(fresh):
    d = process_path(fresh, INV / "01_valid_apex.pdf")
    a = fresh.get("/api/audit", params={"invoice_id": d["id"]}).json()
    assert a["total"] >= 8 and a["items"][0]["timestamp"] and "DECISION_GENERATED" in a["event_types"]
    h = fresh.get("/api/health").json()
    assert h["status"] == "ok" and h["database"] is True and h["extraction_provider"] == "heuristic"
    s = fresh.get("/api/settings").json()
    assert s["policy"]["tolerance_pct"] == "1.0" and "key" not in str(s["extraction"]).replace("configured_keys", "")  # no secrets exposed


def test_samples_and_reset(fresh):
    s = fresh.get("/api/samples").json()["items"]
    assert len(s) == 17 and s[0]["run_order"] == 1
    assert fresh.post("/api/samples/..%2F..%2Fetc%2Fpasswd/load").status_code in (404, 405)  # traversal never reaches the file system
    assert fresh.post("/api/samples/nope.pdf/load").status_code == 404
    d = process_id(fresh, fresh.post("/api/samples/01_valid_apex.pdf/load").json()["id"])
    assert d["final_decision"] == "APPROVED"
    assert fresh.post("/api/admin/reset").status_code == 200
    assert fresh.get("/api/invoices").json()["total"] == 0
    assert next(p for p in fresh.get("/api/purchase-orders").json()["items"] if p["po_number"] == "PO-205")["remaining_balance"] == "59000.00"
