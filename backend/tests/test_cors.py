"""Split deployment: the browser on the frontend's domain must be allowed to call the API (incl. the SSE stream)."""


def preflight(client, origin: str, path: str = "/api/invoices", method: str = "GET"):
    return client.options(path, headers={"Origin": origin, "Access-Control-Request-Method": method, "Access-Control-Request-Headers": "content-type"})


def test_configured_frontend_origin_is_allowed(client):
    r = preflight(client, "https://invoiceiq-frontend.vercel.app", "/api/invoices/1/review", "POST")
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "https://invoiceiq-frontend.vercel.app"
    assert "POST" in r.headers["access-control-allow-methods"]


def test_local_dev_and_preview_urls_allowed(client):
    assert preflight(client, "http://localhost:5173").headers["access-control-allow-origin"] == "http://localhost:5173"
    assert preflight(client, "https://invoiceiq-frontend-git-main-x.vercel.app").status_code == 200


def test_unknown_origin_is_refused_and_actual_requests_carry_headers(client):
    r = preflight(client, "https://evil.example.com")
    assert r.status_code == 400 and "access-control-allow-origin" not in r.headers
    ok = client.get("/api/health", headers={"Origin": "https://invoiceiq-frontend.vercel.app"})
    assert ok.headers["access-control-allow-origin"] == "https://invoiceiq-frontend.vercel.app"
    sse_like = client.get("/api/runs/does-not-exist", headers={"Origin": "https://invoiceiq-frontend.vercel.app"})
    assert sse_like.status_code == 404 and sse_like.headers["access-control-allow-origin"] == "https://invoiceiq-frontend.vercel.app"
