"""Application configuration (environment driven; no secrets in code)."""
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]  # backend/
ROOT_DIR = BASE_DIR.parent  # repo root


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(ROOT_DIR / ".env"), str(BASE_DIR / ".env")), extra="ignore"
    )

    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'invoiceiq.db').as_posix()}"
    upload_dir: Path = BASE_DIR / "data" / "uploads"
    sample_dir: Path = ROOT_DIR / "sample_data"
    frontend_dist: Path = ROOT_DIR / "frontend" / "dist"  # if present, the API also serves the built UI (single-process deploy)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"  # comma-separated exact origins, e.g. https://invoiceiq-frontend.vercel.app
    cors_origin_regex: str | None = None  # optional, e.g. https://invoiceiq-.*\.vercel\.app to also allow preview deployments

    # Upload limits
    max_upload_mb: int = 15
    max_pages: int = 30

    # LLM provider: auto | anthropic | openai | gemini | heuristic
    llm_provider: str = "auto"
    llm_model: str = ""
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 2

    # OCR
    ocr_min_chars_per_page: int = 40
    ocr_low_confidence: float = 0.85

    # Financial policy (documented in docs/BUSINESS_RULES.md)
    tolerance_pct: Decimal = Decimal("1.0")  # % tolerance on price / total variance
    tolerance_abs: Decimal = Decimal("0.00")  # fixed monetary tolerance (0 = disabled)
    rounding_tolerance: Decimal = Decimal("0.05")  # arithmetic rounding allowance
    max_invoice_age_days: int = 365
    future_date_grace_days: int = 1

    # Our company (the buyer). Used to avoid mistaking buyer details for vendor details.
    buyer_name: str = "Northwind Industries Pvt Ltd"
    buyer_tax_id: str = "29AABCN1234F1Z5"

    demo_reviewer: str = "ap.analyst@northwind.demo"

    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    if s.database_url.startswith("sqlite:///"):
        Path(s.database_url.replace("sqlite:///", "", 1)).parent.mkdir(parents=True, exist_ok=True)
    return s
