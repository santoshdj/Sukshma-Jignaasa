"""
Appointment Prep Router — /appointment-prep
-------------------------------------------
Three endpoints:

  1. POST /appointment-prep/start
       Dispatches background task to generate the summary.
       Returns session_id + status="running" immediately.

  2. GET /appointment-prep/{session_id}/status
       Poll until status becomes "awaiting_review" or "failed".

  3. GET /appointment-prep/{session_id}/summary
       Returns the full summary. Only accessible after patient confirmation.

  4. POST /appointment-prep/{session_id}/confirm
       Patient approves ("confirm") or requests a revision ("regenerate").
       On "confirm": status → "confirmed", summary becomes shareable.
       On "regenerate": re-runs node with patient feedback.

Human review gate is non-negotiable — the summary cannot be shared before
the patient explicitly confirms it.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException

import app.agents.appointment_prep_node as _prep_node_mod
from app.agents import session_store
from app.agents.appointment_prep_node import MIN_OBSERVATIONS, appointment_prep_node
from app.models.appointment_prep import (
    AppointmentPrepState,
    AppointmentPrepStatusResponse,
    AppointmentPrepSummary,
    ConfirmAppointmentPrepRequest,
    StartAppointmentPrepRequest,
    StartAppointmentPrepResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/appointment-prep", tags=["Appointment Prep"])

_SESSION_TYPE = "appointment_prep"


def _require_session(session_id: str) -> dict:
    state = session_store.get(session_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"Appointment prep session '{session_id}' not found.",
        )
    return state


async def _run_prep(session_id: str, state: dict) -> None:
    """Background task: generate the summary and persist it."""
    try:
        updates = await asyncio.to_thread(appointment_prep_node, state)
        final_state = {**state, **updates}
    except Exception as exc:
        logger.error("Background appointment_prep_node failed for %s: %s", session_id, exc)
        final_state = {**state, "status": "failed", "errors": state.get("errors", []) + [str(exc)]}

    try:
        await asyncio.to_thread(session_store.save, session_id, _SESSION_TYPE, final_state)
    except Exception as exc:
        logger.error(
            "session_store.save failed for prep session %s (status=%s): %s",
            session_id, final_state.get("status"), exc,
        )


@router.post("/start", response_model=StartAppointmentPrepResponse)
async def start_appointment_prep(
    body: StartAppointmentPrepRequest, background_tasks: BackgroundTasks
) -> StartAppointmentPrepResponse:
    """
    Start appointment prep summary generation.
    Returns immediately with status="running".
    Poll GET /appointment-prep/{session_id}/status for "awaiting_review".
    """
    session_id = str(uuid.uuid4())

    # Quick observation count check — fails fast if no data at all
    observations = await asyncio.to_thread(
        _prep_node_mod._fetch_observations, body.patient_id, 90
    )
    obs_count = len(observations)

    if obs_count < MIN_OBSERVATIONS:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "No observations found — log at least one check-in before generating a prep summary.",
                "observations_available": obs_count,
                "min_observations_required": MIN_OBSERVATIONS,
            },
        )

    initial_state: AppointmentPrepState = {
        "session_id": session_id,
        "patient_id": body.patient_id,
        "observation_count": obs_count,
        "prep_summary": None,
        "human_approved": False,
        "status": "running",
        "errors": [],
    }

    session_store.save(session_id, _SESSION_TYPE, initial_state)
    background_tasks.add_task(_run_prep, session_id, initial_state)

    return StartAppointmentPrepResponse(
        session_id=session_id,
        patient_id=body.patient_id,
        status="running",
        observations_available=obs_count,
    )


@router.get("/{session_id}/status", response_model=AppointmentPrepStatusResponse)
def get_prep_status(session_id: str) -> AppointmentPrepStatusResponse:
    state = _require_session(session_id)
    return AppointmentPrepStatusResponse(
        session_id=session_id,
        patient_id=state.get("patient_id", ""),
        status=state.get("status", "unknown"),
    )


@router.get("/{session_id}/summary", response_model=AppointmentPrepSummary)
def get_prep_summary(session_id: str) -> AppointmentPrepSummary:
    """
    Returns the generated summary.
    Only accessible after the patient has confirmed it (status="confirmed").
    """
    state = _require_session(session_id)

    if state.get("status") == "running":
        raise HTTPException(
            status_code=202,
            detail="Summary is still being generated. Poll /status for updates.",
        )

    if state.get("status") == "awaiting_review":
        raise HTTPException(
            status_code=409,
            detail="Summary not yet confirmed. Call POST /confirm first.",
        )

    if state.get("status") == "failed":
        raise HTTPException(
            status_code=500,
            detail={"message": "Summary generation failed.", "errors": state.get("errors", [])},
        )

    summary_dict = state.get("prep_summary")
    if not summary_dict:
        raise HTTPException(status_code=404, detail="Summary not found.")

    return AppointmentPrepSummary(**summary_dict)


@router.get("/{session_id}/preview", response_model=AppointmentPrepSummary)
def preview_prep_summary(session_id: str) -> AppointmentPrepSummary:
    """
    Returns the generated summary for patient review BEFORE confirmation.
    Only accessible when status="awaiting_review".
    The returned summary has human_approved=False until /confirm is called.
    """
    state = _require_session(session_id)

    if state.get("status") not in ("awaiting_review", "confirmed"):
        raise HTTPException(
            status_code=409,
            detail=f"Summary not ready for preview (status: {state.get('status')}).",
        )

    summary_dict = state.get("prep_summary")
    if not summary_dict:
        raise HTTPException(status_code=404, detail="Summary not found.")

    return AppointmentPrepSummary(**summary_dict)


@router.post("/{session_id}/confirm", response_model=AppointmentPrepStatusResponse)
async def confirm_prep_summary(
    session_id: str,
    body: ConfirmAppointmentPrepRequest,
    background_tasks: BackgroundTasks,
) -> AppointmentPrepStatusResponse:
    """
    Patient confirms the summary (human review gate) or requests a revision.

    "confirm" → status becomes "confirmed"; summary is now shareable.
    "regenerate" → re-runs the node with the patient's feedback.
    """
    state = _require_session(session_id)

    if state.get("status") not in ("awaiting_review",):
        raise HTTPException(
            status_code=409,
            detail=f"Session is not awaiting review (status: {state.get('status')}).",
        )

    if body.decision == "confirm":
        state["human_approved"] = True
        state["status"] = "confirmed"
        # Update the prep_summary to reflect approval
        if state.get("prep_summary"):
            state["prep_summary"]["human_approved"] = True
        await asyncio.to_thread(session_store.save, session_id, _SESSION_TYPE, state)
        return AppointmentPrepStatusResponse(
            session_id=session_id,
            patient_id=state["patient_id"],
            status="confirmed",
        )

    # "regenerate"
    if not body.feedback.strip():
        raise HTTPException(
            status_code=400,
            detail="feedback required when decision='regenerate'.",
        )

    state["human_approved"] = False
    state["status"] = "regenerate"
    state["errors"] = state.get("errors", []) + [f"Patient feedback: {body.feedback}"]

    session_store.save(session_id, _SESSION_TYPE, state)
    background_tasks.add_task(_run_prep, session_id, state)

    return AppointmentPrepStatusResponse(
        session_id=session_id,
        patient_id=state["patient_id"],
        status="running",
    )
