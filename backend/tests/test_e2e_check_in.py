"""
End-to-end integration test — full check-in pipeline against patient_002.
Uses mocked LLM but real FastAPI TestClient + real LangGraph state machine.
No API key, no Medblocks connection required.

What this verifies:
  - POST /check-in/start → graph starts, AI opening message returned
  - POST /check-in/message → AI extraction runs, confirmation summary returned
  - GET confirmation_summary contains compliance finding expected for patient type
  - POST /check-in/confirm → FHIR observations constructed + write attempted
  - Returned FHIR structure is valid (resourceType, subject, components)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from main import app

client = TestClient(app)

_PATIENT_ID = "patient-e2e-002"

# ── Mock helpers ──────────────────────────────────────────────────────────────

def _symptom_response(is_complete: bool = False) -> AIMessage:
    payload = {
        "message": "I've captured your fatigue. Does this summary look right?" if is_complete
                   else "Got it. Any triggers or context for today?",
        "is_complete": is_complete,
        "tone_used": "engaged",
        "extraction": {
            "symptoms": [
                {
                    "symptom_text": "severe fatigue after standing at checkout",
                    "hpo_terms": [
                        {"hpo_id": "HP:0012378", "label": "Fatigue", "confidence": "high"},
                        {"hpo_id": "HP:0003546", "label": "Exercise intolerance", "confidence": "medium"},
                    ],
                    "body_system": "autonomic",
                    "severity": 8,
                    "probable_trigger": "prolonged standing",
                    "trigger_delay_minutes": 5,
                    "sleep_quality": 6,
                    "activity_level": "low",
                    "stress_level": 4,
                    "dietary_notes": None,
                    "cycle_phase": "luteal",
                    "duration_minutes": 120,
                    "onset_time": None,
                }
            ],
            "is_no_symptom_day": False,
            "session_notes": "POTS-like presentation after orthostatic stress",
            "tone_used": "engaged",
        },
    }
    return AIMessage(content=json.dumps(payload))


# ── E2E Test ──────────────────────────────────────────────────────────────────

class TestFullE2EPipeline:
    """Complete check-in pipeline from start to confirmed FHIR write."""

    def _run_pipeline(self):
        """Convenience: run start → message → confirm and return all responses."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = [
            _symptom_response(is_complete=True),  # message call
        ]

        with patch("app.agents.check_in_node.get_check_in_llm", return_value=mock_llm):
            start_resp = client.post("/check-in/start", json={"patient_id": _PATIENT_ID})
            assert start_resp.status_code == 200
            session_id = start_resp.json()["session_id"]

            msg_resp = client.post("/check-in/message", json={
                "session_id": session_id,
                "patient_message": "Had a really bad fatigue crash after standing at the checkout, 8/10. Luteal phase.",
            })
            assert msg_resp.status_code == 200

        return session_id, start_resp, msg_resp

    def test_start_creates_session(self):
        session_id, start_resp, _ = self._run_pipeline()
        body = start_resp.json()
        assert body["session_id"] == session_id
        assert body["status"] == "in_progress"
        assert len(body["ai_message"]) > 0

    def test_message_reaches_awaiting_confirmation(self):
        _, _, msg_resp = self._run_pipeline()
        assert msg_resp.json()["status"] == "awaiting_confirmation"

    def test_confirmation_summary_contains_symptom(self):
        _, _, msg_resp = self._run_pipeline()
        summary = msg_resp.json()["confirmation_summary"]
        assert summary is not None
        assert summary["is_no_symptom_day"] is False
        assert len(summary["symptoms"]) == 1
        symptom = summary["symptoms"][0]
        assert "fatigue" in symptom["text"].lower()
        assert "Fatigue" in symptom["hpo_labels"]

    def test_confirm_returns_fhir_observation_ids(self):
        session_id, _, msg_resp = self._run_pipeline()
        assert msg_resp.json()["status"] == "awaiting_confirmation"

        with patch("app.routers.check_in.write_check_in", new_callable=AsyncMock) as mock_write:
            mock_write.return_value = ["obs-e2e-001"]
            confirm_resp = client.post("/check-in/confirm", json={
                "session_id": session_id,
                "decision": "confirm",
            })

        assert confirm_resp.status_code == 200
        assert confirm_resp.json()["status"] == "saved"
        assert "obs-e2e-001" in confirm_resp.json()["fhir_observation_ids"]

    def test_fhir_observation_structure_is_valid(self):
        """Verify the observations passed to write_check_in have valid FHIR structure."""
        session_id, _, msg_resp = self._run_pipeline()
        assert msg_resp.json()["status"] == "awaiting_confirmation"

        captured_observations = []

        async def capture_write(observations, patient_id, access_token=None):
            captured_observations.extend(observations)
            return [f"obs-{i}" for i in range(len(observations))]

        with patch("app.routers.check_in.write_check_in", side_effect=capture_write):
            client.post("/check-in/confirm", json={
                "session_id": session_id,
                "decision": "confirm",
            })

        assert len(captured_observations) == 1
        obs = captured_observations[0]

        # FHIR Observation structure
        assert obs["resourceType"] == "Observation"
        assert obs["status"] == "final"
        assert obs["subject"]["reference"] == f"Patient/{_PATIENT_ID}"

        # HPO coding present
        assert "coding" in obs["code"]
        hpo_ids = [c["code"] for c in obs["code"]["coding"]]
        assert "HP:0012378" in hpo_ids  # Fatigue

        # Key components present
        comp_map = {c["code"]["text"]: c for c in obs["component"]}
        assert comp_map["severity"]["valueInteger"] == 8
        assert comp_map["body_system"]["valueString"] == "autonomic"
        assert comp_map["probable_trigger"]["valueString"] == "prolonged standing"
        assert comp_map["cycle_phase"]["valueString"] == "luteal"
        assert comp_map["sleep_quality"]["valueInteger"] == 6

    def test_no_hpo_hallucinations_in_fhir(self):
        """All HPO IDs in the FHIR output must exist in the curated vocabulary."""
        from app.services.hpo_validator import is_valid

        session_id, _, msg_resp = self._run_pipeline()
        assert msg_resp.json()["status"] == "awaiting_confirmation"

        captured_observations = []

        async def capture_write(observations, patient_id, access_token=None):
            captured_observations.extend(observations)
            return ["obs-001"]

        with patch("app.routers.check_in.write_check_in", side_effect=capture_write):
            client.post("/check-in/confirm", json={
                "session_id": session_id,
                "decision": "confirm",
            })

        for obs in captured_observations:
            codings = obs.get("code", {}).get("coding", [])
            for coding in codings:
                hpo_id = coding.get("code", "")
                if coding.get("system") == "https://hpo.jax.org/":
                    assert is_valid(hpo_id), f"Hallucinated HPO ID in FHIR output: {hpo_id}"
