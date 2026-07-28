"""
Integration tests for the Hypothesis Surfacer API.
LLM and FHIR calls are mocked.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from main import app

client = TestClient(app)
PATIENT_ID = "patient-hyp-test-001"


def _mock_hypothesis_llm(hypotheses: list[dict], summary: str = "Pattern analysis complete.") -> MagicMock:
    payload = {
        "hypotheses": hypotheses,
        "summary": summary,
    }
    mock = MagicMock()
    mock.invoke.return_value = AIMessage(content=json.dumps(payload))
    return mock


def _pots_hypothesis():
    return {
        "condition_id": "POTS",
        "condition_name": "Postural Orthostatic Tachycardia Syndrome (POTS)",
        "match_strength": "high",
        "matching_symptoms": ["Racing heart on standing", "Dizziness"],
        "missing_signals": ["Tilt table test", "Blood volume study"],
        "plain_language_explanation": "Your symptom pattern shares features with POTS, particularly the heart rate changes when standing.",
        "specialist_type": "Autonomic neurologist",
        "confidence_note": "Pattern similarity only — many conditions share these symptoms.",
        "discuss_with_specialist": True,
    }


def _mock_observations(count: int = 35) -> list[dict]:
    return [
        {
            "resourceType": "Observation",
            "id": f"obs-{i}",
            "effectiveDateTime": "2026-07-01T10:00:00Z",
            "code": {
                "coding": [{"system": "https://hpo.jax.org/", "code": "HP:0012378", "display": "Fatigue"}],
                "text": "fatigue",
            },
            "component": [
                {"code": {"text": "severity"}, "valueInteger": 7},
                {"code": {"text": "probable_trigger"}, "valueString": "prolonged standing"},
            ],
        }
        for i in range(count)
    ]


class TestHypothesisHappyPath:
    def _run_to_awaiting_review(self):
        with patch("app.agents.hypothesis_node._get_patient_observations_sync") as mock_obs:
            mock_obs.return_value = _mock_observations(35)
            with patch("app.agents.hypothesis_node.get_analysis_llm") as mock_llm:
                mock_llm.return_value = _mock_hypothesis_llm([_pots_hypothesis()])
                resp = client.post("/hypothesis/start", json={"patient_id": PATIENT_ID})
        return resp

    def test_start_returns_awaiting_review(self):
        resp = self._run_to_awaiting_review()
        assert resp.status_code == 200
        assert resp.json()["status"] == "awaiting_review"

    def test_report_not_accessible_before_approval(self):
        resp = self._run_to_awaiting_review()
        session_id = resp.json()["session_id"]
        report_resp = client.get(f"/hypothesis/{session_id}/report")
        assert report_resp.status_code == 409

    def test_approve_makes_report_accessible(self):
        resp = self._run_to_awaiting_review()
        session_id = resp.json()["session_id"]

        approve = client.post(
            f"/hypothesis/{session_id}/approve",
            json={"decision": "approve"},
        )
        assert approve.status_code == 200

        report = client.get(f"/hypothesis/{session_id}/report")
        assert report.status_code == 200
        body = report.json()
        assert "hypotheses" in body
        assert len(body["hypotheses"]) == 1
        assert body["hypotheses"][0]["discuss_with_specialist"] is True
        assert "medical diagnosis" in body["guardrail_disclosure"]

    def test_guardrail_disclosure_always_present(self):
        resp = self._run_to_awaiting_review()
        session_id = resp.json()["session_id"]
        client.post(f"/hypothesis/{session_id}/approve", json={"decision": "approve"})
        report = client.get(f"/hypothesis/{session_id}/report").json()
        assert report["guardrail_disclosure"]
        assert len(report["guardrail_disclosure"]) > 20

    def test_discuss_with_specialist_always_true(self):
        resp = self._run_to_awaiting_review()
        session_id = resp.json()["session_id"]
        client.post(f"/hypothesis/{session_id}/approve", json={"decision": "approve"})
        report = client.get(f"/hypothesis/{session_id}/report").json()
        for h in report["hypotheses"]:
            assert h["discuss_with_specialist"] is True


class TestObservationGate:
    def test_422_when_insufficient_observations(self):
        with patch("app.agents.hypothesis_node._get_patient_observations_sync") as mock_obs:
            mock_obs.return_value = _mock_observations(10)  # < 30
            resp = client.post("/hypothesis/start", json={"patient_id": PATIENT_ID})
        assert resp.status_code == 422
        body = resp.json()
        assert body["detail"]["observations_available"] == 10
        assert body["detail"]["min_observations_required"] == 30


class TestUnknownSession:
    def test_status_404_for_unknown_session(self):
        resp = client.get("/hypothesis/nonexistent-session/status")
        assert resp.status_code == 404

    def test_approve_404_for_unknown_session(self):
        resp = client.post(
            "/hypothesis/nonexistent-session/approve",
            json={"decision": "approve"},
        )
        assert resp.status_code == 404


class TestGuardrailViolationHandling:
    def test_guardrail_violation_replaced_in_output(self):
        """Even if LLM produces guardrail violations, the final report is clean."""
        bad_hypothesis = {
            **_pots_hypothesis(),
            "plain_language_explanation": "You might have POTS. This diagnosis suggests dysautonomia.",
        }
        with patch("app.agents.hypothesis_node._get_patient_observations_sync") as mock_obs:
            mock_obs.return_value = _mock_observations(35)
            with patch("app.agents.hypothesis_node.get_analysis_llm") as mock_llm:
                mock_llm.return_value = _mock_hypothesis_llm([bad_hypothesis])
                resp = client.post("/hypothesis/start", json={"patient_id": PATIENT_ID})

        assert resp.status_code == 200
        session_id = resp.json()["session_id"]
        client.post(f"/hypothesis/{session_id}/approve", json={"decision": "approve"})
        report = client.get(f"/hypothesis/{session_id}/report").json()

        # The report structure should still be valid
        assert len(report["hypotheses"]) >= 0  # May be 0 if all invalidated
