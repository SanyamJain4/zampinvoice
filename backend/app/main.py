import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import data, invoices, runs
from app.core.config import get_settings
from app.database.session import SessionLocal, init_db
from app.services import seeder, workflow_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("invoiceiq")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as db:
        if not seeder.is_seeded(db):
            if (settings.sample_dir / "vendors.csv").exists():
                counts = seeder.seed_from_csv(db, settings.sample_dir)
                log.info("Seeded master data: %s", counts)
            else:
                log.warning("No master data found. Run `python scripts/generate_sample_data.py` then `python scripts/seed_database.py`.")
    n = workflow_service.recover_interrupted_runs()
    if n:
        log.warning("Marked %d interrupted run(s) as failed", n)
    yield


app = FastAPI(title="InvoiceIQ", version="1.0.0", description="AI-assisted invoice processing: PDF -> extraction -> deterministic checks -> explainable decision. "
              "Makes decisions only; it never executes payments.", lifespan=lifespan)
# The browser needs permission when the UI (e.g. on Vercel) and the API live on different domains.
# No cookies are used, so credentials are not enabled; origins come from CORS_ORIGINS (+ optional CORS_ORIGIN_REGEX).
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list(), allow_origin_regex=settings.cors_origin_regex,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(invoices.router)
app.include_router(runs.router)
app.include_router(data.router)


def _mount_frontend() -> None:
    """Serve the built React app (if `npm run build` has been run) so one process / one port is enough."""
    dist = settings.frontend_dist.resolve()
    if not (dist / "index.html").exists():
        return
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(404, "Not found.")
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and dist in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")  # client-side routing


_mount_frontend()


@app.exception_handler(StarletteHTTPException)
async def http_exc(_: Request, exc: StarletteHTTPException):
    detail = exc.detail
    body = detail if isinstance(detail, dict) else {"message": str(detail)}
    return JSONResponse(status_code=exc.status_code, content={"error": True, **body})


@app.exception_handler(RequestValidationError)
async def validation_exc(_: Request, exc: RequestValidationError):
    errs = [{"field": ".".join(str(p) for p in e["loc"][1:]), "problem": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"error": True, "message": "Some of the submitted values are not valid.", "fields": errs})


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"error": True, "message": "Something went wrong on the server. The error has been logged."})
