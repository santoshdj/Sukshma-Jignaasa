"""
Hypothesis Router — /hypothesis
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException

from app.agents.hypothesis_graph import hypothesis_graph
from app.agents.hypothesis_node import MIN_OBSERVATIONS
from app.models.hypothesis import (
    ApproveHypothesisRequest,
    HypothesisReport,
    HypothesisState,
    HypothesisStatusResponse,
    StartHypothesisRequest,
    StartHypothesisResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/hypothesis", tags=["Hypothesis Surfacer"])


def _config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


def _get_state(session_id: str) -> dict:
    snapshot = hypothesis_graph.get_state(_config(session_id))
    if not snapshot or not snapshot.values:
        raise HTTPException(status_code=404, detail=f"Hypothesis session '{session_id}' not found.")
    return snapshot.values


def _run_graph(config: dict, input_: dict | None) -> None:
    for _ in hypothesis_graph.stream(input_, config):
        pass


@router.post("/start", response_model=StartHypothesisResponse)
async def start_hypothesis(body: StartHypothesisRequest) -> StartHypothesisResponse:
    """
    Start hypothesis analysis for a patient.
    Returns 422 if patient has < 30 observations.
    Graph runs until it hits the review_gate interrupt.
    """
    session_id = str(uuid.uuid4())
    config = _config(session_id)

    initial_state: HypothesisState = {
        "session_id": session_id,
        "patient_id": body.patient_id,
        "symptom_fingerprint": {},
        "ehr_context": {},
        "observation_count": 0,
        "retrieved_profiles": [],
        "hypothesis_report": None,
        "human_approved": False,
        "status": "running",
        "errors": [],
    }

    try:
        _run_graph(config, initial_state)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    state = _get_state(session_id)

    if state.get("status") == "failed":
        errors = state.get("errors", [])
        # Gate check: insufficient observations
        if any("observations" in e for e in errors):
            obs_count = state.get("observation_count", 0)
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Insufficient symptom data",
                    "observations_available": obs_count,
                    "min_observations_required": MIN_OBSERVATIONS,
                },
            )
        raise HTTPException(status_code=500, detail={"errors": errors})

    return StartHypothesisResponse(
        session_id=session_id,
        patient_id=body.patient_id,
        status=state.get("status", "awaiting_review"),
        observations_available=state.get("observation_count", 0),
        min_observations_required=MIN_OBSERVATIONS,
    )


@router.get("/{session_id}/status", response_model=HypothesisStatusResponse)
def get_hypothesis_status(session_id: str) -> HypothesisStatusResponse:
    state = _get_state(session_id)
    return HypothesisStatusResponse(
        session_id=session_id,
        patient_id=state.get("patient_id", ""),
        status=state.get("status", "unknown"),
    )


@router.get("/{session_id}/report", response_model=HypothesisReport)
def get_hypothesis_report(session_id: str) -> HypothesisReport:
    """Returns the full report. Only accessible after patient approval."""
    state = _get_state(session_id)
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
def approve_hypothesis(session_id: str, body: ApproveHypothesisRequest) -> HypothesisStatusResponse:
    """Patient approves or requests regeneration of the hypothesis report."""
    config = _config(session_id)
    state = _get_state(session_id)

    if state.get("status") not in ("awaiting_review",):
        raise HTTPException(
            status_code=409,
            detail=f"Session is not awaiting review (status: {state.get('status')}).",
        )

    if body.decision == "approve":
        hypothesis_graph.update_state(config, {"human_approved": True, "status": "approved"})
        _run_graph(config, None)
        return HypothesisStatusResponse(session_id=session_id, patient_id=state["patient_id"], status="approved")

    # regenerate
    if not body.feedback.strip():
        raise HTTPException(status_code=400, detail="feedback required when decision='regenerate'.")

    hypothesis_graph.update_state(config, {
        "human_approved": False,
        "status": "regenerate",
        "errors": state.get("errors", []) + [f"Patient feedback: {body.feedback}"],
    })
    try:
        _run_graph(config, None)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    updated = _get_state(session_id)
    return HypothesisStatusResponse(
        session_id=session_id,
        patient_id=state["patient_id"],
        status=updated.get("status", "awaiting_review"),
    )
