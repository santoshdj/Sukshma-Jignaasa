"""
Check-In Router — /check-in
----------------------------
Three endpoints drive the full daily check-in session flow:

  1. POST /check-in/start
       Initialise state, run check_in_node (opening message), save to session store.
       Returns: session_id + AI opening message.

  2. POST /check-in/message
       Append patient message to state, run check_in_node, save updated state.
       Returns: AI message + status.
       When status="awaiting_confirmation": also returns confirmation_summary.

  3. POST /check-in/confirm
       Patient confirms or requests edit.
       On "confirm": FHIR write → delete session → return observation IDs.
       On "edit":    append edit note → re-run check_in_node → save → return AI response.

State persistence is handled by session_store (SQLite-backed).
The "human-in-the-loop interrupt" is the HTTP response boundary — no graph framework needed.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.agents import session_store
from app.agents.check_in_node import check_in_node
from app.models.check_in import (
    CheckInExtraction,
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

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/check-in", tags=["Check-In"])

_SESSION_TYPE = "check_in"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_session(session_id: str) -> dict:
    """Return stored state or raise 404."""
    state = session_store.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return state


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


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/start", response_model=StartCheckInResponse, status_code=200)
def start_check_in(body: StartCheckInRequest) -> StartCheckInResponse:
    """
    Start a new check-in session.
    Runs the AI opening turn (hardcoded greeting — no LLM call) and saves state.
    """
    session_id = str(uuid.uuid4())

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
        updates = check_in_node(initial_state)
    except Exception as exc:
        logger.error("start_check_in node error for session %s: %s", session_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    state = {**initial_state, **updates}
    session_store.save(session_id, _SESSION_TYPE, state)

    return StartCheckInResponse(
        session_id=session_id,
        ai_message=_last_ai_message(state),
        status=state.get("status", "in_progress"),
    )


@router.post("/message", response_model=CheckInMessageResponse)
def send_message(body: CheckInMessageRequest) -> CheckInMessageResponse:
    """
    Send the patient's message and get the AI's response.
    When the AI has enough information, returns status='awaiting_confirmation'
    plus a structured confirmation_summary.
    """
    state = _require_session(body.session_id)

    current_status = state.get("status", "in_progress")
    if current_status in ("awaiting_confirmation", "saved", "filed"):
        raise HTTPException(
            status_code=409,
            detail=f"Session is in '{current_status}' state — use POST /check-in/confirm.",
        )

    state["conversation_history"] = list(state.get("conversation_history", [])) + [
        {"role": "user", "content": body.patient_message}
    ]

    try:
        updates = check_in_node(state)
    except Exception as exc:
        logger.error("send_message node error for session %s: %s", body.session_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    state = {**state, **updates}
    session_store.save(body.session_id, _SESSION_TYPE, state)

    new_status = state.get("status", "in_progress")
    confirmation_summary = None
    if new_status == "awaiting_confirmation":
        confirmation_summary = _build_confirmation_summary(state)

    return CheckInMessageResponse(
        ai_message=_last_ai_message(state),
        status=new_status,
        confirmation_summary=confirmation_summary,
    )


@router.post("/confirm", response_model=ConfirmCheckInResponse)
async def confirm_check_in(body: ConfirmCheckInRequest) -> ConfirmCheckInResponse:
    """
    Patient reviews the confirmation summary and either:
      - Confirms ("confirm"): FHIR observations are written, session is deleted.
      - Requests edit ("edit"): AI re-opens for correction.
    """
    state = _require_session(body.session_id)

    if state.get("status") != "awaiting_confirmation":
        raise HTTPException(
            status_code=409,
            detail=f"Session is not awaiting confirmation (status: {state.get('status')}).",
        )

    if body.decision == "edit":
        if not (body.edit_notes or "").strip():
            raise HTTPException(status_code=400, detail="edit_notes required when decision='edit'.")

        state["conversation_history"] = list(state.get("conversation_history", [])) + [
            {"role": "user", "content": f"Please update: {body.edit_notes}"}
        ]
        state["human_confirmed"] = False
        state["status"] = "in_progress"

        try:
            updates = check_in_node(state)
        except Exception as exc:
            logger.error("confirm edit node error for session %s: %s", body.session_id, exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        state = {**state, **updates}
        session_store.save(body.session_id, _SESSION_TYPE, state)

        return ConfirmCheckInResponse(
            status=state.get("status", "in_progress"),
            fhir_observation_ids=[],
        )

    # decision == "confirm"
    extraction_dict = state.get("current_extraction") or {}
    fhir_ids: list[str] = []

    try:
        extraction = CheckInExtraction(**extraction_dict) if extraction_dict else None
        if extraction:
            observations = extraction_to_observations(
                extraction,
                patient_id=state["patient_id"],
                check_in_time=datetime.now(timezone.utc),
            )
            fhir_ids = await write_check_in(observations, state["patient_id"])
    except Exception as exc:
        logger.error("FHIR write failed for session %s: %s", body.session_id, exc)
        # Don't raise — return partial success with empty fhir_ids

    session_store.delete(body.session_id)

    return ConfirmCheckInResponse(
        status="saved",
        fhir_observation_ids=fhir_ids,
    )
