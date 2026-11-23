"""Optional live check against a real LLM provider. Skipped unless an API key is present in the environment.

    ANTHROPIC_API_KEY=... pytest backend/tests/test_live_smoke.py -s
"""
import pytest

from app.core.config import Settings
from app.services import ai_extractor, pdf_processor
from tests.conftest import LIVE_KEYS, SAMPLE_DIR

provider = next((p for p, k in (("anthropic", "ANTHROPIC_API_KEY"), ("openai", "OPENAI_API_KEY"), ("gemini", "GEMINI_API_KEY")) if k in LIVE_KEYS), None)


@pytest.mark.skipif(provider is None, reason="no LLM API key in the environment")
@pytest.mark.parametrize("file, number, total", [("01_valid_apex.pdf", "APX/2026/1187", "59000.00"), ("14_multipage_keystone.pdf", "KHT-3390", "175224.10")])
def test_live_llm_extracts_real_invoices(file, number, total):
    kwargs = {f"{provider}_api_key": LIVE_KEYS[f"{provider.upper()}_API_KEY"]}
    s = Settings(_env_file=None, llm_provider=provider, **kwargs)
    doc = pdf_processor.extract_document(SAMPLE_DIR / "invoices" / file, s)
    res = ai_extractor.extract_invoice([p.lines for p in doc.pages], s)
    assert res.method == f"llm:{provider}"
    assert res.extracted.invoice_number == number
    assert str(res.extracted.grand_total) == total or float(res.extracted.grand_total) == float(total)
    assert res.extracted.po_number and res.extracted.vendor_name
