"""Test environment: isolated temp DB + uploads, freshly generated synthetic data, deterministic (non-LLM) extraction."""
import importlib.util
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

_tmp = Path(tempfile.mkdtemp(prefix="invoiceiq-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["UPLOAD_DIR"] = str(_tmp / "uploads")
os.environ["SAMPLE_DIR"] = str(_tmp / "sample_data")
os.environ["LLM_PROVIDER"] = "heuristic"
os.environ["CORS_ORIGINS"] = "https://invoiceiq-frontend.vercel.app,http://localhost:5173"
os.environ["CORS_ORIGIN_REGEX"] = r"https://invoiceiq-frontend-.*\.vercel\.app"
# Keep any real keys aside for the optional live smoke test; the regular suite never touches the network.
LIVE_KEYS = {k: os.environ.pop(k) for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY") if os.environ.get(k)}

spec = importlib.util.spec_from_file_location("generate_sample_data", ROOT / "scripts" / "generate_sample_data.py")
gen = importlib.util.module_from_spec(spec)
sys.modules["generate_sample_data"] = gen
spec.loader.exec_module(gen)
MANIFEST = gen.write_all(_tmp / "sample_data")
SAMPLE_DIR = _tmp / "sample_data"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def fresh(client):
    """A freshly seeded database for each test."""
    r = client.post("/api/admin/reset")
    assert r.status_code == 200, r.text
    return client


def wait_run(client, run_id: str, timeout: float = 180.0) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in ("COMPLETED", "FAILED"):
            return run
        time.sleep(0.15)
    raise TimeoutError(f"run {run_id} did not finish")


def process_path(client, path: Path, force: bool = False) -> dict:
    with open(path, "rb") as fh:
        up = client.post("/api/invoices/upload", files={"file": (path.name, fh, "application/pdf")})
    assert up.status_code == 201, up.text
    inv_id = up.json()["id"]
    return process_id(client, inv_id, force)


def process_id(client, inv_id: int, force: bool = False) -> dict:
    r = client.post(f"/api/invoices/{inv_id}/process", json={"force": force})
    assert r.status_code == 200, r.text
    run = wait_run(client, r.json()["run_id"])
    detail = client.get(f"/api/invoices/{inv_id}").json()
    detail["_run"] = run
    return detail


def rule(detail: dict, rule_id: str) -> dict:
    return next(v for v in detail["validations"] if v["rule_id"] == rule_id)
