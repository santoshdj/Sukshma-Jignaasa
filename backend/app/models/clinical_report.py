"""
Clinical Report request / response models.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class GenerateReportRequest(BaseModel):
    patient_id: str = Field(..., min_length=1)
    prep_session_id: str | None = Field(
        None,
        description="Confirmed appointment-prep session to include in the report.",
    )
    hypothesis_session_id: str | None = Field(
        None,
        description="Approved hypothesis session to include in the report.",
    )

    @classmethod
    def model_post_init(cls, __context: object) -> None:  # noqa: N802
        pass  # validation handled in router


class GenerateReportResponse(BaseModel):
    """Returned when content-type negotiation prefers JSON over PDF."""

    patient_id: str
    sections_included: list[str]
    filename: str
