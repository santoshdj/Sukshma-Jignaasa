"""
Hypothesis Router — /hypothesis
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException

import app.agents.hypothesis_node as _hyp_node
from app.agents import session_store
from app.agents.hypothesis_node import MIN_OBSERVATIONS, hypothesis_node
from app.models.hypothesis import (
    ApproveHypothesisRequest,
    HypothesisReport,
    HypothesisState,
    HypothesisStatusResponse,
    StartHypothesisRequest,
    StartHypothesisResponse,
)
from pydantic import BaseModel


class HypothesisSessionSummary(BaseModel):
    """Lightweight session row for the patient's analysis history list."""
    session_id: str
    status: str
    created_at: str | None
    updated_at: str | None
    observation_count: int
    hypothesis_count: int
    human_approved: bool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/hypothesis", tags=["Hypothesis Surfacer"])

_SESSION_TYPE = "hypothesis"


def _require_session(session_id: str) -> dict:
    state = session_store.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Hypothesis session '{session_id}' not found.")
    return state


async def _run_analysis(session_id: str, state: dict) -> None:
    """Background task: run hypothesis_node and persist the result."""
    try:
        updates = await asyncio.to_thread(hypothesis_node, state)
        final_state = {**state, **updates}
    except Exception as exc:
        logger.error("Background hypothesis analysis failed for %s: %s", session_id, exc)
        final_state = {**state, "status": "failed", "errors": state.get("errors", []) + [str(exc)]}

    # Run the DB write in a thread so it doesn't block the event loop and avoids
    # SQLite write/read contention with concurrent sync routes in the thread pool.
    try:
        await asyncio.to_thread(session_store.save, session_id, _SESSION_TYPE, final_state)
    except Exception as exc:
        logger.error(
            "session_store.save failed for hypothesis session %s (status=%s): %s",
            session_id, final_state.get("status"), exc,
        )


@router.post("/start", response_model=StartHypothesisResponse)
async def start_hypothesis(
    body: StartHypothesisRequest, background_tasks: BackgroundTasks
) -> StartHypothesisResponse:
    """
    Start hypothesis analysis for a patient.
    Returns 422 immediately if patient has < 30 observations.
    Otherwise returns 200 with status="running" and dispatches the
    ChromaDB + LLM work as a background task.
    Poll GET /hypothesis/{session_id}/status until "awaiting_review" before fetching the report.
    """
    session_id = str(uuid.uuid4())

    # Observation gate: run synchronously so we can return 422 without a round-trip
    observations = await asyncio.to_thread(
        _hyp_node._get_patient_observations_sync, body.patient_id
    )
    fingerprint = _hyp_node._build_symptom_fingerprint(observations)
    obs_count = fingerprint.get("observation_count", 0)

    if obs_count < MIN_OBSERVATIONS:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Insufficient symptom data",
                "observations_available": obs_count,
                "min_observations_required": MIN_OBSERVATIONS,
            },
        )

    # Pre-populate fingerprint so the background task skips the FHIR re-fetch
    initial_state: HypothesisState = {
        "session_id": session_id,
        "patient_id": body.patient_id,
        "symptom_fingerprint": fingerprint,
        "ehr_context": {},
        "observation_count": obs_count,
        "retrieved_profiles": [],
        "hypothesis_report": None,
        "human_approved": False,
        "status": "running",
        "errors": [],
    }

    session_store.save(session_id, _SESSION_TYPE, initial_state)
    background_tasks.add_task(_run_analysis, session_id, initial_state)

    return StartHypothesisResponse(
        session_id=session_id,
        patient_id=body.patient_id,
        status="running",
        observations_available=obs_count,
        min_observations_required=MIN_OBSERVATIONS,
    )


@router.get("/patient/{patient_id}/sessions", response_model=list[HypothesisSessionSummary])
def list_patient_sessions(patient_id: str) -> list[HypothesisSessionSummary]:
    """
    Return all hypothesis sessions for a patient, newest first.
    Used by the frontend "My analyses" page.
    """
    rows = session_store.list_for_patient(patient_id, _SESSION_TYPE)
    return [HypothesisSessionSummary(**r) for r in rows]


@router.get("/{session_id}/status", response_model=HypothesisStatusResponse)
def get_hypothesis_status(session_id: str) -> HypothesisStatusResponse:
    state = _require_session(session_id)
    return HypothesisStatusResponse(
        session_id=session_id,
        patient_id=state.get("patient_id", ""),
        status=state.get("status", "unknown"),
    )


@router.get("/{session_id}/report", response_model=HypothesisReport)
def get_hypothesis_report(session_id: str) -> HypothesisReport:
    """Returns the full report. Only accessible after patient approval."""
    state = _require_session(session_id)
    if not state.get("human_approved"):
        raise HTTPException(
            status_code=409,
            detail="Report not yet approved. Call POST /hypothesis/{id}/approve first.",
        )
    report_dict = state.get("hypothesis_report")
    if not report_dict:
        raise HTTPException(status_code=404, detail="Report not found.")
    return HypothesisReport(**report_dict)


@router.post("/{session_id}/approve", response_model=HypothesisStatusResponse)
async def approve_hypothesis(session_id: str, body: ApproveHypothesisRequest) -> HypothesisStatusResponse:
    """Patient approves or requests regeneration of the hypothesis report."""
    state = _require_session(session_id)

    if state.get("status") not in ("awaiting_review",):
        raise HTTPException(
            status_code=409,
            detail=f"Session is not awaiting review (status: {state.get('status')}).",
        )

    if body.decision == "approve":
        state["human_approved"] = True
        state["status"] = "approved"
        session_store.save(session_id, _SESSION_TYPE, state)
        return HypothesisStatusResponse(
            session_id=session_id,
            patient_id=state["patient_id"],
            status="approved",
        )

    # regenerate
    if not body.feedback.strip():
        raise HTTPException(status_code=400, detail="feedback required when decision='regenerate'.")

    state["human_approved"] = False
    state["status"] = "regenerate"
    state["errors"] = state.get("errors", []) + [f"Patient feedback: {body.feedback}"]

    try:
        updates = await asyncio.to_thread(hypothesis_node, state)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    state = {**state, **updates}
    session_store.save(session_id, _SESSION_TYPE, state)

    return HypothesisStatusResponse(
        session_id=session_id,
        patient_id=state["patient_id"],
        status=state.get("status", "awaiting_review"),
    )
