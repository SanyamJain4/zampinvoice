from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class CorrectionRequest(BaseModel):
    corrections: dict[str, Any] = Field(..., description="Field -> corrected value (whitelisted fields only)")
    reason: str = Field(..., min_length=5, max_length=1000)
    reviewer: str = Field(default="ap.analyst@northwind.demo", min_length=3, max_length=120)


class ReviewRequest(BaseModel):
    action: Literal["APPROVE", "REJECT", "REQUEST_CLARIFICATION"]
    justification: str = Field(..., min_length=10, max_length=2000)
    reviewer: str = Field(default="ap.analyst@northwind.demo", min_length=3, max_length=120)

    @field_validator("justification")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class ProcessRequest(BaseModel):
    force: bool = False
    actor: str = "ap.analyst@northwind.demo"
