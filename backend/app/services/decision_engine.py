"""Turns deterministic rule results into one explainable decision.

APPROVED       all mandatory controls PASS
REJECTED       a confirmed hard-block rule failed (confirmed duplicate, blocked vendor)
NEEDS_REVIEW   anything else that is FAIL / REVIEW, or any mandatory control that could not be evaluated
(PROCESSING_ERROR is produced by the workflow when the pipeline itself fails; it is not a business decision.)
The LLM is never consulted here.
"""
from __future__ import annotations

from decimal import Decimal

from app.services.common import money
from app.services.validation_engine import Ctx, RuleResult

SEV = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
MANDATORY = {"R01", "R02", "R03", "R04", "R05", "R06", "R08", "R09", "R10", "R14", "R15", "R16"}
# Controls a human reviewer may NOT override (fix the data via correction, or amend the PO / vendor master instead).
NON_BYPASSABLE = {"R01", "R02", "R03", "R04", "R05", "R09", "R10", "R14"}

NEXT_ACTION = {
    "R01": "Obtain the missing information from the vendor (or correct the extraction from the PDF) and re-run validation.",
    "R02": "Procurement must verify / re-activate the vendor in the vendor master before this invoice can be paid.",
    "R03": "Confirm the correct PO with the requester or vendor, correct the PO reference, and re-run validation.",
    "R04": "Verify with procurement whether the PO reference is a typo or the invoice was misdirected; correct the PO reference or reject.",
    "R05": "Confirm the billing currency with the vendor; a conversion policy or a corrected invoice is required.",
    "R06": "Ask the vendor for a corrected invoice, or correct the extracted values if the extraction was wrong.",
    "R07": "Check the line items against the PDF; request a corrected invoice if the vendor's arithmetic is wrong.",
    "R08": "Confirm whether this is a genuine second invoice; if it is a duplicate, reject it.",
    "R09": "The invoice exceeds the PO authorization. Request a PO amendment from procurement or a corrected invoice.",
    "R10": "Insufficient PO balance. Request a PO amendment from procurement or ask the vendor to re-issue for the remaining amount.",
    "R11": "Check prices with procurement; approve with justification only if the price difference is agreed.",
    "R12": "Check the tax calculation; request a corrected invoice if the tax is wrong.",
    "R13": "Check the invoice date with the vendor.",
    "R14": "The PO is closed or fully invoiced. Procurement must re-open or amend the PO.",
    "R15": "Compare the extracted values with the original PDF and correct anything that was misread.",
    "R16": "Map the billed items to PO lines manually, or ask the vendor for an itemised invoice.",
}


def _first_sentence(s: str, limit: int = 220) -> str:
    s = s.strip()
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def decide(rules: list[RuleResult], ctx: Ctx) -> dict:
    by_id = {r.rule_id: r for r in rules}
    counts = {"PASS": 0, "FAIL": 0, "REVIEW": 0, "NOT_APPLICABLE": 0}
    for r in rules:
        counts[r.status] += 1
    hard = [r for r in rules if r.hard_block and r.status == "FAIL"]
    flagged = sorted([r for r in rules if r.status in ("FAIL", "REVIEW")], key=lambda r: (SEV[r.severity], r.rule_id))
    unevaluated = [i for i in sorted(MANDATORY) if by_id.get(i) and by_id[i].status == "NOT_APPLICABLE"]

    corrected = bool(ctx.corrected_fields)
    allocation = None
    if hard:
        status = "REJECTED"
        top = sorted(hard, key=lambda r: (SEV[r.severity], r.rule_id))[0]
        main = f"{top.rule_name}: {_first_sentence(top.explanation)}"
        reasons = [f"{r.rule_id} {r.rule_name}: {r.explanation}" for r in flagged]
        manual = False
        nxt = ("Do not pay. No further action is needed; the original invoice has already been handled."
               if top.rule_id == "R08" else "Do not pay. Escalate to Procurement / Compliance.")
    elif flagged:
        status = "NEEDS_REVIEW"
        top = flagged[0]
        main = f"{top.rule_name}: {_first_sentence(top.explanation)}"
        reasons = [f"{r.rule_id} {r.rule_name}: {r.explanation}" for r in flagged]
        manual = True
        nxt = NEXT_ACTION.get(top.rule_id, "Review the flagged checks.")
    elif unevaluated:
        status = "NEEDS_REVIEW"
        main = f"Mandatory control(s) could not be evaluated: {', '.join(unevaluated)}."
        reasons = [main]
        manual = True
        nxt = "Complete the missing information and re-run validation."
    elif corrected:
        status = "NEEDS_REVIEW"
        main = ("All automated checks pass on reviewer-corrected data. Policy: corrected invoices need an explicit "
                "reviewer approval; they are never auto-approved.")
        reasons = [main]
        manual = True
        nxt = "Approve with a justification (the checks will be re-run under the PO lock)."
    else:
        status = "APPROVED"
        r10 = by_id["R10"].details
        po = ctx.po.po
        allocation = {
            "po_number": po.po_number, "currency": po.currency, "invoice_total": str(ctx.ex.grand_total),
            "remaining_before": r10.get("remaining_before"), "remaining_after": r10.get("remaining_after"),
        }
        main = (f"All {counts['PASS']} applicable checks passed: vendor {ctx.vendor.vendor.legal_name} verified, "
                f"PO {po.po_number} matched, no duplicate, amounts reconcile.")
        reasons = [f"{r.rule_id} {r.rule_name}: {r.observed}" for r in rules if r.status == "PASS"]
        manual = False
        nxt = (f"Ready for the payment run (this system does not execute payments). "
               f"PO {po.po_number} balance after this invoice: {money(Decimal(r10['remaining_after']), po.currency)}.")

    sev = "NONE"
    if flagged:
        sev = flagged[0].severity
    evidence = []
    for f, e in (ctx.ex.evidence or {}).items():
        evidence.append({"field": f, "page": e.page, "snippet": e.snippet})
    explanation = main if status == "APPROVED" else (
        main + (" Other issues: " + "; ".join(f"{r.rule_id}" for r in flagged[1:]) + "." if len(flagged) > 1 else ""))
    return {
        "status": status,
        "main_reason": main,
        "detailed_reasons": reasons,
        "explanation": explanation,
        "requires_manual_intervention": manual,
        "recommended_next_action": nxt,
        "severity": sev,
        "rules_summary": counts,
        "hard_blocks": [r.rule_id for r in hard],
        "flagged_rules": [r.rule_id for r in flagged],
        "allocation": allocation,
        "evidence": evidence,
        "corrected_data": corrected,
    }


def blocking_controls(rules: list[RuleResult]) -> list[RuleResult]:
    """Rules that stop a MANUAL approval (hard financial controls cannot be silently bypassed)."""
    out = []
    for r in rules:
        if r.status in ("FAIL", "REVIEW") and (r.rule_id in NON_BYPASSABLE or (r.hard_block and r.status == "FAIL")):
            out.append(r)
    return out
