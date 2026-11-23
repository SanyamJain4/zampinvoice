"""The LLM path is exercised with a mocked HTTP layer (deterministic, no network)."""
import httpx
import pytest

from app.core.config import Settings
from app.services import ai_extractor
from app.services.ai_extractor import ExtractionError

PAGES = [["Acme Ltd", "Invoice No: A-1"]]
GOOD = {"vendor_name": "Acme Ltd", "invoice_number": "A-1", "invoice_date": "2026-11-01", "po_number": "PO-1", "currency": "INR",
        "subtotal": "100.00", "tax_amount": "18.00", "grand_total": "118.00", "line_items": [{"description": "x", "quantity": "1", "unit_price": "100.00", "line_total": "100.00"}]}


def cfg(**kw) -> Settings:
    base = dict(llm_provider="anthropic", anthropic_api_key="test-key", llm_max_retries=2)
    return Settings(_env_file=None, **{**base, **kw})


def resp(status=200, body=None):
    return httpx.Response(status, json=body or {}, request=httpx.Request("POST", "https://api.test"))


def tool_use(payload):
    return resp(200, {"content": [{"type": "tool_use", "name": "record_invoice", "input": payload}]})


def test_provider_resolution(monkeypatch):
    assert ai_extractor.resolve_provider(Settings(_env_file=None, llm_provider="auto", anthropic_api_key=None, openai_api_key=None, gemini_api_key=None))[0] == "heuristic"
    assert ai_extractor.resolve_provider(cfg())[0] == "anthropic"
    with pytest.raises(ExtractionError) as e:
        ai_extractor.resolve_provider(Settings(_env_file=None, llm_provider="openai", openai_api_key=None))
    assert e.value.code == "MISSING_API_KEY" and "OPENAI_API_KEY" in e.value.user_message
    assert "sk-" not in e.value.user_message


def test_successful_structured_extraction(monkeypatch):
    sent = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.update(json=json, headers=headers)
        return tool_use(GOOD)

    monkeypatch.setattr(ai_extractor.httpx, "post", fake_post)
    res = ai_extractor.extract_invoice(PAGES, cfg())
    assert res.extracted.grand_total == 118 and res.method == "llm:anthropic" and res.attempts == 1
    assert sent["json"]["tool_choice"]["name"] == "record_invoice"  # strict structured output
    assert "<invoice_text" in sent["json"]["messages"][0]["content"]


def test_bounded_retry_on_transient_errors_then_success(monkeypatch):
    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        return resp(429) if len(calls) < 3 else tool_use(GOOD)

    monkeypatch.setattr(ai_extractor.httpx, "post", fake_post)
    res = ai_extractor.extract_invoice(PAGES, cfg(), sleep=lambda s: None)
    assert res.attempts == 3


def test_retries_are_bounded_and_failure_is_not_faked(monkeypatch):
    calls = []
    monkeypatch.setattr(ai_extractor.httpx, "post", lambda *a, **k: calls.append(1) or resp(503))
    with pytest.raises(ExtractionError) as e:
        ai_extractor.extract_invoice(PAGES, cfg(llm_max_retries=1), sleep=lambda s: None)
    assert len(calls) == 2 and e.value.code == "AI_UNAVAILABLE"  # no fabricated fallback extraction


def test_timeout_is_retried(monkeypatch):
    def boom(*a, **k):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(ai_extractor.httpx, "post", boom)
    with pytest.raises(ExtractionError) as e:
        ai_extractor.extract_invoice(PAGES, cfg(llm_max_retries=1), sleep=lambda s: None)
    assert "timeout" in str(e.value).lower()


def test_rejected_api_key_does_not_retry_and_hides_key(monkeypatch):
    calls = []
    monkeypatch.setattr(ai_extractor.httpx, "post", lambda *a, **k: calls.append(1) or resp(401))
    with pytest.raises(ExtractionError) as e:
        ai_extractor.extract_invoice(PAGES, cfg(), sleep=lambda s: None)
    assert len(calls) == 1 and e.value.code == "API_KEY_REJECTED" and "test-key" not in e.value.user_message


def test_invalid_json_from_model_is_retried(monkeypatch):
    seq = [resp(200, {"content": [{"type": "text", "text": "sorry"}]}), tool_use(GOOD)]
    monkeypatch.setattr(ai_extractor.httpx, "post", lambda *a, **k: seq.pop(0))
    assert ai_extractor.extract_invoice(PAGES, cfg(), sleep=lambda s: None).attempts == 2


def test_model_output_is_normalised_and_missing_never_invented(monkeypatch):
    payload = {**GOOD, "invoice_number": None, "grand_total": "1,18,000.00", "evidence": {"grand_total": {"page": 1, "snippet": "Total 1,18,000.00"}}}
    monkeypatch.setattr(ai_extractor.httpx, "post", lambda *a, **k: tool_use(payload))
    ex = ai_extractor.extract_invoice(PAGES, cfg()).extracted
    assert ex.invoice_number is None and "invoice_number" in ex.missing_fields
    assert ex.grand_total == 118000 and ex.evidence["grand_total"].page == 1
