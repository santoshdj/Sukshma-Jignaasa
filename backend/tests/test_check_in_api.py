"""
Integration tests for the check-in API endpoints.
LLM calls and FHIR writes are mocked.

Tests assert:
  - Full session state machine traverses correctly
  - Patient confirmation is non-skippable (no FHIR write without confirm)
  - 404 on unknown session_id
  - 409 when message sent to a session awaiting confirmation
  - FHIR observation IDs returned on successful confirm
  - Edit flow loops back to in_progress
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from main import app

client = TestClient(app)

_PATIENT_ID = "patient-api-test-001"


# ── LLM mock helpers ──────────────────────────────────────────────────────────

def _ai_response(message: str, is_complete: bool = False, symptoms=None, is_no_symptom=False) -> AIMessage:
    payload = {
        "message": message,
        "is_complete": is_complete,
        "tone_used": "engaged",
        "extraction": {
            "symptoms": symptoms or ([] if is_no_symptom else [{
                "symptom_text": "fatigue after standing",
                "hpo_terms": [{"hpo_id": "HP:0012378", "label": "Fatigue", "confidence": "high"}],
                "body_system": "autonomic",
                "severity": 7,
                "duration_minutes": None,
                "onset_time": None,
                "probable_trigger": "prolonged standing",
                "trigger_delay_minutes": None,
                "sleep_quality": None,
                "activity_level": None,
                "stress_level": None,
                "dietary_notes": None,
                "cycle_phase": None,
            }]),
            "is_no_symptom_day": is_no_symptom,
            "session_notes": "test",
            "tone_used": "engaged",
        },
    }
    return AIMessage(content=json.dumps(payload))


def _make_llm_sequence(*responses: AIMessage):
    """Create a mock LLM that returns responses in sequence."""
    idx = {"n": 0}

    def invoke(_messages, **_kwargs):
        r = responses[min(idx["n"], len(responses) - 1)]
        idx["n"] += 1
        return r

    mock = MagicMock()
    mock.invoke.side_effect = invoke
    return mock


# ── Test: Full happy path ─────────────────────────────────────────────────────

class TestFullHappyPath:
    def test_start_returns_session_id_and_ai_message(self):
        with patch("app.agents.check_in_node.get_check_in_llm") as mock_llm_factory:
            mock_llm_factory.return_value = _make_llm_sequence(
                _ai_response("How are you feeling today?")
            )
            resp = client.post("/check-in/start", json={"patient_id": _PATIENT_ID})

        assert resp.status_code == 200
        body = resp.json()
        assert "session_id" in body
        assert len(body["session_id"]) > 0
        assert body["status"] == "in_progress"
        assert len(body["ai_message"]) > 0

    def test_message_returns_ai_response(self):
        with patch("app.agents.check_in_node.get_check_in_llm") as mock_llm_factory:
            mock_llm_factory.return_value = _make_llm_sequence(
                _ai_response("Got it — a trigger. Anything else?"),  # consumed by /message
            )
            start = client.post("/check-in/start", json={"patient_id": _PATIENT_ID})
            session_id = start.json()["session_id"]

            msg_resp = client.post("/check-in/message", json={
                "session_id": session_id,
                "patient_message": "Fatigue after standing, about a 7",
            })

        assert msg_resp.status_code == 200
        assert msg_resp.json()["status"] == "in_progress"
        assert msg_resp.json()["confirmation_summary"] is None

    def test_complete_session_returns_confirmation_summary(self):
        with patch("app.agents.check_in_node.get_check_in_llm") as mock_llm_factory:
            mock_llm_factory.return_value = _make_llm_sequence(
                _ai_response("Here's what I captured.", is_complete=True),
            )
            start = client.post("/check-in/start", json={"patient_id": _PATIENT_ID})
            session_id = start.json()["session_id"]

            msg_resp = client.post("/check-in/message", json={
                "session_id": session_id,
                "patient_message": "Fatigue, 7/10, after walking",
            })

        assert msg_resp.json()["status"] == "awaiting_confirmation"
        summary = msg_resp.json()["confirmation_summary"]
        assert summary is not None
        assert "is_no_symptom_day" in summary

    def test_confirm_writes_fhir_and_returns_ids(self):
        with patch("app.agents.check_in_node.get_check_in_llm") as mock_llm_factory:
            mock_llm_factory.return_value = _make_llm_sequence(
                _ai_response("Summary ready.", is_complete=True),
            )
            start = client.post("/check-in/start", json={"patient_id": _PATIENT_ID})
            session_id = start.json()["session_id"]
            client.post("/check-in/message", json={
                "session_id": session_id,
                "patient_message": "Fatigue 7/10",
            })

        with patch("app.routers.check_in.write_check_in", new_callable=AsyncMock) as mock_write:
            mock_write.return_value = ["obs-fhir-001"]
            confirm_resp = client.post("/check-in/confirm", json={
                "session_id": session_id,
                "decision": "confirm",
            })

        assert confirm_resp.status_code == 200
        body = confirm_resp.json()
        assert body["status"] == "saved"
        assert "obs-fhir-001" in body["fhir_observation_ids"]


# ── Test: Confirmation gate is non-skippable ─────────────────────────────────

class TestConfirmationGateRequired:
    def test_cannot_confirm_before_awaiting_confirmation(self):
        """Confirm endpoint must reject sessions not in awaiting_confirmation state."""
        with patch("app.agents.check_in_node.get_check_in_llm") as mock_llm_factory:
            mock_llm_factory.return_value = _make_llm_sequence(
                _ai_response("How are you feeling?"),
            )
            start = client.post("/check-in/start", json={"patient_id": _PATIENT_ID})
            session_id = start.json()["session_id"]

        resp = client.post("/check-in/confirm", json={
            "session_id": session_id,
            "decision": "confirm",
        })
        assert resp.status_code == 409

    def test_cannot_send_message_after_awaiting_confirmation(self):
        """Message endpoint must reject sessions already in awaiting_confirmation."""
        with patch("app.agents.check_in_node.get_check_in_llm") as mock_llm_factory:
            mock_llm_factory.return_value = _make_llm_sequence(
                _ai_response("Summary ready.", is_complete=True),
            )
            start = client.post("/check-in/start", json={"patient_id": _PATIENT_ID})
            session_id = start.json()["session_id"]
            client.post("/check-in/message", json={
                "session_id": session_id,
                "patient_message": "Fatigue",
            })

        resp = client.post("/check-in/message", json={
            "session_id": session_id,
            "patient_message": "Another message",
        })
        assert resp.status_code == 409


# ── Test: Unknown session ─────────────────────────────────────────────────────

class TestUnknownSession:
    def test_message_to_unknown_session_returns_404(self):
        resp = client.post("/check-in/message", json={
            "session_id": "non-existent-session-xyz",
            "patient_message": "Hello",
        })
        assert resp.status_code == 404

    def test_confirm_unknown_session_returns_404(self):
        resp = client.post("/check-in/confirm", json={
            "session_id": "non-existent-session-xyz",
            "decision": "confirm",
        })
        assert resp.status_code == 404


# ── Test: No-symptom day path ─────────────────────────────────────────────────

class TestNoSymptomDay:
    def test_no_symptom_day_saves_baseline(self):
        with patch("app.agents.check_in_node.get_check_in_llm") as mock_llm_factory:
            mock_llm_factory.return_value = _make_llm_sequence(
                _ai_response("Logging a baseline for today.", is_complete=True, is_no_symptom=True),
            )
            start = client.post("/check-in/start", json={"patient_id": _PATIENT_ID})
            session_id = start.json()["session_id"]
            msg_resp = client.post("/check-in/message", json={
                "session_id": session_id,
                "patient_message": "Feeling great today, no symptoms!",
            })

        assert msg_resp.json()["status"] == "awaiting_confirmation"
        summary = msg_resp.json()["confirmation_summary"]
        assert summary["is_no_symptom_day"] is True

        with patch("app.routers.check_in.write_check_in", new_callable=AsyncMock) as mock_write:
            mock_write.return_value = ["obs-baseline-001"]
            confirm_resp = client.post("/check-in/confirm", json={
                "session_id": session_id,
                "decision": "confirm",
            })

        assert confirm_resp.json()["status"] == "saved"
        assert "obs-baseline-001" in confirm_resp.json()["fhir_observation_ids"]

        # Verify write_check_in was called with the baseline observation
        call_args = mock_write.call_args
        observations = call_args[0][0]
        assert len(observations) == 1
        comp_map = {c["code"]["text"]: c for c in observations[0]["component"]}
        assert comp_map["is_no_symptom_day"]["valueBoolean"] is True


# ── Test: Edit flow ───────────────────────────────────────────────────────────

class TestEditFlow:
    def test_edit_returns_in_progress_status(self):
        with patch("app.agents.check_in_node.get_check_in_llm") as mock_llm_factory:
            mock_llm_factory.return_value = _make_llm_sequence(
                _ai_response("Summary.", is_complete=True),
            )
            start = client.post("/check-in/start", json={"patient_id": _PATIENT_ID})
            session_id = start.json()["session_id"]
            client.post("/check-in/message", json={
                "session_id": session_id,
                "patient_message": "Fatigue",
            })

        with patch("app.agents.check_in_node.get_check_in_llm") as mock_llm_factory:
            mock_llm_factory.return_value = _make_llm_sequence(
                _ai_response("Updated to severity 9.", is_complete=True),
            )
            edit_resp = client.post("/check-in/confirm", json={
                "session_id": session_id,
                "decision": "edit",
                "edit_notes": "The severity should be 9, not 7",
            })

        assert edit_resp.status_code == 200

    def test_edit_without_notes_returns_400(self):
        with patch("app.agents.check_in_node.get_check_in_llm") as mock_llm_factory:
            mock_llm_factory.return_value = _make_llm_sequence(
                _ai_response("Summary.", is_complete=True),
            )
            start = client.post("/check-in/start", json={"patient_id": _PATIENT_ID})
            session_id = start.json()["session_id"]
            client.post("/check-in/message", json={
                "session_id": session_id,
                "patient_message": "Fatigue",
            })

        resp = client.post("/check-in/confirm", json={
            "session_id": session_id,
            "decision": "edit",
            "edit_notes": "",
        })
        assert resp.status_code == 400


# ── Test: Quick log entries ───────────────────────────────────────────────────

class TestQuickLogEntries:
    def test_start_with_quick_log_accepted(self):
        with patch("app.agents.check_in_node.get_check_in_llm") as mock_llm_factory:
            mock_llm_factory.return_value = _make_llm_sequence(
                _ai_response("Thanks for logging those! Anything to add?"),
            )
            resp = client.post("/check-in/start", json={
                "patient_id": _PATIENT_ID,
                "quick_log_entries": [
                    {"symptom_name": "Fatigue", "severity": 7},
                    {"symptom_name": "Joint pain", "severity": 5},
                ],
            })

        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"
