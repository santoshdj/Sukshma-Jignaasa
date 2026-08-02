"""
Clinical Report Router — /clinical-report
------------------------------------------
Single endpoint:

  POST /clinical-report/generate
       Validates the referenced sessions, builds the PDF synchronously
       (reportlab < 1 s), and returns it as an inline PDF download.

       Requires at least one of:
         - prep_session_id   → must be in status="confirmed"
         - hypothesis_session_id → must have human_approved=True

       Both can be included together for a combined report.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.agents import session_store
from app.models.clinical_report import GenerateReportRequest
from app.services.pdf_service import generate_clinical_report_pdf

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/clinical-report", tags=["Clinical Report"])


def _require_prep_session(session_id: str) -> dict:
    """Return the prep session state or raise a descriptive error."""
    state = session_store.get(session_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Appointment prep session '{session_id}' not found.",
        )
    if state.get("status") != "confirmed":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Appointment prep session '{session_id}' has not been confirmed "
                f"(status: '{state.get('status')}'). "
                "Confirm the summary first via POST /appointment-prep/{id}/confirm."
            ),
        )
    prep_summary = state.get("prep_summary")
    if not prep_summary:
        raise HTTPException(
            status_code=404,
            detail=f"Appointment prep session '{session_id}' has no summary.",
        )
    return prep_summary


def _require_hypothesis_session(session_id: str) -> dict:
    """Return the hypothesis report dict or raise a descriptive error."""
    state = session_store.get(session_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Hypothesis session '{session_id}' not found.",
        )
    if not state.get("human_approved"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Hypothesis session '{session_id}' has not been approved "
                f"(status: '{state.get('status')}'). "
                "Approve the report first via POST /hypothesis/{id}/approve."
            ),
        )
    report = state.get("hypothesis_report")
    if not report:
        raise HTTPException(
            status_code=404,
            detail=f"Hypothesis session '{session_id}' has no report.",
        )
    return report


@router.post("/generate")
def generate_report(body: GenerateReportRequest) -> StreamingResponse:
    """
    Generate a clinical report PDF.

    Requires at least one confirmed session reference.
    Returns the PDF as an attachment download.
    """
    if not body.prep_session_id and not body.hypothesis_session_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "At least one of prep_session_id or hypothesis_session_id is required. "
                "Generate and confirm an appointment prep summary or approve a hypothesis "
                "report before requesting a clinical report."
            ),
        )

    prep_summary: dict | None = None
    hypothesis_report: dict | None = None

    if body.prep_session_id:
        prep_summary = _require_prep_session(body.prep_session_id)

    if body.hypothesis_session_id:
        hypothesis_report = _require_hypothesis_session(body.hypothesis_session_id)

    try:
        pdf_bytes = generate_clinical_report_pdf(
            patient_id=body.patient_id,
            prep_summary=prep_summary,
            hypothesis_report=hypothesis_report,
        )
    except Exception as exc:
        logger.error("PDF generation failed for patient %s: %s", body.patient_id, exc)
        raise HTTPException(status_code=500, detail="PDF generation failed.") from exc

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"sukshma-jignaasa-report-{body.patient_id[:8]}-{date_str}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
