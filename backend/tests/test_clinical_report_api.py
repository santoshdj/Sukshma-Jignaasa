"""
Integration tests for the Clinical Report endpoint.

Tests assert:
  - PDF is generated when a confirmed prep session is provided
  - PDF is generated when an approved hypothesis session is provided
  - PDF is generated when both sessions are provided (combined report)
  - 422 when neither session_id is supplied
  - 404 when prep session does not exist
  - 404 when hypothesis session does not exist
  - 409 when prep session is not in "confirmed" status
  - 409 when hypothesis session is not approved
  - Response has correct Content-Type and Content-Disposition headers
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from main import app

client = TestClient(app)
PATIENT_ID = "patient-report-test-001"


# ── Fixtures: seed confirmed sessions ─────────────────────────────────────────

def _mock_prep_llm_response() -> MagicMock:
    payload = {
        "top_symptoms": [
            {
                "name": "Fatigue",
                "hpo_id": "HP:0012378",
                "body_system": "autonomic",
                "frequency": 10,
                "avg_severity": 7.0,
                "last_observed": "2026-07-30",
            }
        ],
        "trigger_patterns": [
            {
                "symptom": "Fatigue",
                "trigger": "prolonged standing",
                "description": "Fatigue frequently follows standing.",
                "frequency_label": "frequently",
            }
        ],
        "suggested_questions": [
            {
                "question": "Could my fatigue pattern relate to orthostatic changes?",
                "context": "Fatigue follows standing in most logs.",
            }
        ],
        "narrative": "Over the past 90 days fatigue was the most prominent symptom.",
    }
    mock = MagicMock()
    mock.invoke.return_value = AIMessage(content=json.dumps(payload))
    return mock


def _mock_observations(count: int = 10) -> list[dict]:
    return [
        {
            "resourceType": "Observation",
            "effectiveDateTime": "2026-07-01T10:00:00Z",
            "subject": {"reference": f"Patient/{PATIENT_ID}"},
            "code": {
                "coding": [{"system": "https://hpo.jax.org/", "code": "HP:0012378", "display": "Fatigue"}],
                "text": "fatigue",
            },
            "component": [
                {"code": {"text": "severity"}, "valueInteger": 7},
                {"code": {"text": "body_system"}, "valueString": "autonomic"},
            ],
        }
        for _ in range(count)
    ]


def _mock_hypothesis_llm_response() -> MagicMock:
    payload = {
        "hypotheses": [
            {
                "condition_id": "POTS",
                "condition_name": "Postural Orthostatic Tachycardia Syndrome",
                "match_strength": "high",
                "matching_symptoms": ["Fatigue", "Dizziness"],
                "missing_signals": ["Tilt table test"],
                "plain_language_explanation": "Your symptom pattern shares features with POTS.",
                "specialist_type": "Autonomic neurologist",
                "confidence_note": "Pattern similarity only — not a diagnosis.",
                "discuss_with_specialist": True,
            }
        ],
        "summary": "Your symptom pattern shows features that may be worth discussing with a specialist.",
    }
    mock = MagicMock()
    mock.invoke.return_value = AIMessage(content=json.dumps(payload))
    return mock


def _create_confirmed_prep_session() -> str:
    with patch("app.agents.appointment_prep_node._fetch_observations") as mock_obs:
        mock_obs.return_value = _mock_observations(10)
        with patch("app.agents.appointment_prep_node.get_analysis_llm") as mock_llm:
            mock_llm.return_value = _mock_prep_llm_response()
            resp = client.post("/appointment-prep/start", json={"patient_id": PATIENT_ID})
    session_id = resp.json()["session_id"]
    client.post(f"/appointment-prep/{session_id}/confirm", json={"decision": "confirm"})
    return session_id


def _create_approved_hypothesis_session() -> str:
    with patch("app.agents.hypothesis_node._get_patient_observations_sync") as mock_obs:
        mock_obs.return_value = _mock_observations(35)
        with patch("app.agents.hypothesis_node.get_analysis_llm") as mock_llm:
            mock_llm.return_value = _mock_hypothesis_llm_response()
            resp = client.post("/hypothesis/start", json={"patient_id": PATIENT_ID})
    session_id = resp.json()["session_id"]
    client.post(f"/hypothesis/{session_id}/approve", json={"decision": "approve"})
    return session_id


# ── PDF content helper ────────────────────────────────────────────────────────

def _is_pdf(content: bytes) -> bool:
    return content[:4] == b"%PDF"


# ── Tests: happy path ─────────────────────────────────────────────────────────

class TestHappyPath:
    def test_generate_from_prep_only(self):
        session_id = _create_confirmed_prep_session()
        resp = client.post("/clinical-report/generate", json={
            "patient_id": PATIENT_ID,
            "prep_session_id": session_id,
        })
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert "attachment" in resp.headers["content-disposition"]
        assert _is_pdf(resp.content)

    def test_generate_from_hypothesis_only(self):
        session_id = _create_approved_hypothesis_session()
        resp = client.post("/clinical-report/generate", json={
            "patient_id": PATIENT_ID,
            "hypothesis_session_id": session_id,
        })
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert _is_pdf(resp.content)

    def test_generate_combined_report(self):
        prep_id = _create_confirmed_prep_session()
        hyp_id = _create_approved_hypothesis_session()
        resp = client.post("/clinical-report/generate", json={
            "patient_id": PATIENT_ID,
            "prep_session_id": prep_id,
            "hypothesis_session_id": hyp_id,
        })
        assert resp.status_code == 200
        assert _is_pdf(resp.content)
        # Combined report is larger than single-source reports
        single_prep = client.post("/clinical-report/generate", json={
            "patient_id": PATIENT_ID,
            "prep_session_id": prep_id,
        })
        assert len(resp.content) > len(single_prep.content)

    def test_filename_contains_patient_id_prefix(self):
        session_id = _create_confirmed_prep_session()
        resp = client.post("/clinical-report/generate", json={
            "patient_id": PATIENT_ID,
            "prep_session_id": session_id,
        })
        cd = resp.headers["content-disposition"]
        assert PATIENT_ID[:8] in cd

    def test_pdf_is_non_empty(self):
        session_id = _create_confirmed_prep_session()
        resp = client.post("/clinical-report/generate", json={
            "patient_id": PATIENT_ID,
            "prep_session_id": session_id,
        })
        assert len(resp.content) > 1000  # valid PDF is always > 1 KB


# ── Tests: validation errors ──────────────────────────────────────────────────

class TestValidationErrors:
    def test_422_when_no_session_ids(self):
        resp = client.post("/clinical-report/generate", json={
            "patient_id": PATIENT_ID,
        })
        assert resp.status_code == 422

    def test_404_when_prep_session_not_found(self):
        resp = client.post("/clinical-report/generate", json={
            "patient_id": PATIENT_ID,
            "prep_session_id": "nonexistent-session",
        })
        assert resp.status_code == 404

    def test_404_when_hypothesis_session_not_found(self):
        resp = client.post("/clinical-report/generate", json={
            "patient_id": PATIENT_ID,
            "hypothesis_session_id": "nonexistent-session",
        })
        assert resp.status_code == 404


# ── Tests: confirmation gates ─────────────────────────────────────────────────

class TestConfirmationGates:
    def test_409_when_prep_not_confirmed(self):
        """Prep session in awaiting_review cannot be used for a report."""
        with patch("app.agents.appointment_prep_node._fetch_observations") as mock_obs:
            mock_obs.return_value = _mock_observations(10)
            with patch("app.agents.appointment_prep_node.get_analysis_llm") as mock_llm:
                mock_llm.return_value = _mock_prep_llm_response()
                start_resp = client.post("/appointment-prep/start", json={"patient_id": PATIENT_ID})
        session_id = start_resp.json()["session_id"]
        # Deliberately do NOT confirm — status remains "awaiting_review"

        resp = client.post("/clinical-report/generate", json={
            "patient_id": PATIENT_ID,
            "prep_session_id": session_id,
        })
        assert resp.status_code == 409

    def test_409_when_hypothesis_not_approved(self):
        """Hypothesis session in awaiting_review cannot be used for a report."""
        with patch("app.agents.hypothesis_node._get_patient_observations_sync") as mock_obs:
            mock_obs.return_value = _mock_observations(35)
            with patch("app.agents.hypothesis_node.get_analysis_llm") as mock_llm:
                mock_llm.return_value = _mock_hypothesis_llm_response()
                start_resp = client.post("/hypothesis/start", json={"patient_id": PATIENT_ID})
        session_id = start_resp.json()["session_id"]
        # Deliberately do NOT approve

        resp = client.post("/clinical-report/generate", json={
            "patient_id": PATIENT_ID,
            "hypothesis_session_id": session_id,
        })
        assert resp.status_code == 409
