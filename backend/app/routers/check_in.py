"""
Check-In Router — /check-in
----------------------------
Three endpoints drive the full daily check-in session flow:

  1. POST /check-in/start
       Initialise state, run ai_turn (opening message), pause at human_turn.
       Returns: session_id + AI opening message.

  2. POST /check-in/message
       Inject patient message, resume graph, run ai_turn.
       Returns: AI message + status.
       When status="awaiting_confirmation": also returns confirmation_summary.

  3. POST /check-in/confirm
       Patient confirms or requests edit.
       On "confirm": resume graph → END → FHIR write → return observation IDs.
       On "edit": resume graph → loops back to ai_turn with edit context.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.agents.check_in_graph import check_in_graph
from app.models.check_in import (
    CheckInState,
    ConfirmCheckInRequest,
    ConfirmCheckInResponse,
    ConfirmationSummary,
    StartCheckInRequest,
    StartCheckInResponse,
    CheckInMessageRequest,
    CheckInMessageResponse,
)
from app.services.fhir_writer import extraction_to_observations, write_check_in
from app.models.check_in import CheckInExtraction

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/check-in", tags=["Check-In"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


def _get_state(session_id: str) -> dict:
    snapshot = check_in_graph.get_state(_config(session_id))
    if not snapshot or not snapshot.values:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return snapshot.values


def _last_ai_message(state: dict) -> str:
    history = state.get("conversation_history", [])
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            return msg.get("content", "")
    return ""


def _build_confirmation_summary(state: dict) -> ConfirmationSummary:
    """Build a structured human-readable summary from the current extraction."""
    extraction = state.get("current_extraction") or {}
    symptoms = extraction.get("symptoms", [])
    is_no_symptom = extraction.get("is_no_symptom_day", False)

    symptom_summaries = []
    for s in symptoms:
        hpo_labels = [t.get("label", "") for t in s.get("hpo_terms", []) if t.get("label")]
        symptom_summaries.append({
            "text": s.get("symptom_text", ""),
            "hpo_labels": hpo_labels,
            "severity": s.get("severity"),
            "body_system": s.get("body_system"),
            "trigger": s.get("probable_trigger"),
        })

    context: dict = {}
    if symptoms:
        first = symptoms[0]
        if first.get("sleep_quality") is not None:
            context["sleep_quality"] = first["sleep_quality"]
        if first.get("stress_level") is not None:
            context["stress_level"] = first["stress_level"]
        if first.get("activity_level"):
            context["activity_level"] = first["activity_level"]

    if is_no_symptom:
        msg = "No symptoms today — logging a baseline for your records."
    elif symptom_summaries:
        count = len(symptom_summaries)
        top = symptom_summaries[0]["text"]
        msg = f"I've captured {count} symptom{'s' if count > 1 else ''} including: {top}."
    else:
        msg = "I've captured your check-in. Does this look right?"

    return ConfirmationSummary(
        symptoms=symptom_summaries,
        context=context,
        is_no_symptom_day=is_no_symptom,
        message=msg,
    )


def _run_graph_until_interrupt(config: dict, input_: dict | None) -> None:
    """Stream the graph until it hits an interrupt or END. Consumes all events."""
    for _ in check_in_graph.stream(input_, config):
        pass


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/start", response_model=StartCheckInResponse, status_code=200)
def start_check_in(body: StartCheckInRequest) -> StartCheckInResponse:
    """
    Start a new check-in session.
    Runs the AI opening turn and pauses at human_turn waiting for the patient.
    """
    session_id = str(uuid.uuid4())
    config = _config(session_id)

    initial_state: CheckInState = {
        "session_id": session_id,
        "patient_id": body.patient_id,
        "quick_log_entries": [e.model_dump() for e in body.quick_log_entries],
        "conversation_history": [],
        "turn_count": 0,
        "current_extraction": {},
        "tone_mode": "engaged",
        "confirmation_summary": None,
        "human_confirmed": False,
        "fhir_observation_ids": [],
        "status": "in_progress",
        "errors": [],
    }

    try:
        _run_graph_until_interrupt(config, initial_state)
    except Exception as exc:
        logger.error("start_check_in graph error for session %s: %s", session_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    state = _get_state(session_id)
    ai_message = _last_ai_message(state)

    return StartCheckInResponse(
        session_id=session_id,
        ai_message=ai_message,
        status=state.get("status", "in_progress"),
    )


@router.post("/message", response_model=CheckInMessageResponse)
def send_message(body: CheckInMessageRequest) -> CheckInMessageResponse:
    """
    Send the patient's message and get the AI's response.
    When the AI has enough information, returns status='awaiting_confirmation'
    plus a structured confirmation_summary.
    """
    config = _config(body.session_id)
    state = _get_state(body.session_id)

    current_status = state.get("status", "in_progress")
    if current_status in ("awaiting_confirmation", "saved", "filed"):
        raise HTTPException(
            status_code=409,
            detail=f"Session is in '{current_status}' state — use POST /check-in/confirm.",
        )

    # Inject patient message into state
    history = list(state.get("conversation_history", []))
    history.append({"role": "user", "content": body.patient_message})
    check_in_graph.update_state(config, {"conversation_history": history})

    try:
        _run_graph_until_interrupt(config, None)
    except Exception as exc:
        logger.error("send_message graph error for session %s: %s", body.session_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    updated_state = _get_state(body.session_id)
    ai_message = _last_ai_message(updated_state)
    new_status = updated_state.get("status", "in_progress")

    confirmation_summary = None
    if new_status == "awaiting_confirmation":
        confirmation_summary = _build_confirmation_summary(updated_state)

    return CheckInMessageResponse(
        ai_message=ai_message,
        status=new_status,
        confirmation_summary=confirmation_summary,
    )


@router.post("/confirm", response_model=ConfirmCheckInResponse)
async def confirm_check_in(body: ConfirmCheckInRequest) -> ConfirmCheckInResponse:
    """
    Patient reviews the confirmation summary and either:
      - Confirms ("confirm"): FHIR observations are written, session is complete.
      - Requests edit ("edit"): AI re-opens for correction.
    """
    config = _config(body.session_id)
    state = _get_state(body.session_id)

    if state.get("status") != "awaiting_confirmation":
        raise HTTPException(
            status_code=409,
            detail=f"Session is not awaiting confirmation (status: {state.get('status')}).",
        )

    if body.decision == "edit":
        if not (body.edit_notes or "").strip():
            raise HTTPException(status_code=400, detail="edit_notes required when decision='edit'.")

        # Inject edit request back into conversation as a user message
        history = list(state.get("conversation_history", []))
        history.append({
            "role": "user",
            "content": f"Please update: {body.edit_notes}",
        })
        check_in_graph.update_state(config, {
            "conversation_history": history,
            "human_confirmed": False,
            "status": "in_progress",
        })
        _run_graph_until_interrupt(config, None)

        updated_state = _get_state(body.session_id)
        ai_message = _last_ai_message(updated_state)
        return ConfirmCheckInResponse(
            status=updated_state.get("status", "in_progress"),
            fhir_observation_ids=[],
        )

    # decision == "confirm"
    check_in_graph.update_state(config, {
        "human_confirmed": True,
        "status": "filed",
    })

    try:
        _run_graph_until_interrupt(config, None)
    except Exception as exc:
        logger.error("confirm graph error for session %s: %s", body.session_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    final_state = _get_state(body.session_id)
    extraction_dict = final_state.get("current_extraction") or {}

    # Write to FHIR
    fhir_ids: list[str] = []
    try:
        extraction = CheckInExtraction(**extraction_dict) if extraction_dict else None
        if extraction:
            observations = extraction_to_observations(
                extraction,
                patient_id=final_state["patient_id"],
                check_in_time=datetime.now(timezone.utc),
            )
            fhir_ids = await write_check_in(observations, final_state["patient_id"])
    except Exception as exc:
        logger.error("FHIR write failed for session %s: %s", body.session_id, exc)
        # Don't raise — return partial success with empty fhir_ids

    # Store IDs back in state
    check_in_graph.update_state(config, {"fhir_observation_ids": fhir_ids})

    return ConfirmCheckInResponse(
        status="saved",
        fhir_observation_ids=fhir_ids,
    )
