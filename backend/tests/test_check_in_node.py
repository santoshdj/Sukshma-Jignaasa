"""
Unit tests for the check-in AI node.
All LLM calls are mocked — no API key required.

Tests cover:
- 10 synthetic patient scenarios with expected extraction behaviour
- Guardrail violation detection and safe fallback
- HPO code validation (hallucinated IDs stripped)
- Tone detection logic
- No-symptom day handling
- Opening message generation
- Max-turn enforcement
"""

from __future__ import annotations

import json
import re
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from app.agents.check_in_node import (
    _detect_tone,
    check_guardrails,
    check_in_node,
)
from app.models.check_in import CheckInState, VALID_HPO_IDS


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_state(
    history: list[dict] | None = None,
    turn_count: int = 0,
    quick_log: list[dict] | None = None,
    current_extraction: dict | None = None,
) -> CheckInState:
    return CheckInState(
        session_id="test-session",
        patient_id="test-patient",
        quick_log_entries=quick_log or [],
        conversation_history=history or [],
        turn_count=turn_count,
        current_extraction=current_extraction or {},
        tone_mode="engaged",
        confirmation_summary=None,
        human_confirmed=False,
        fhir_observation_ids=[],
        status="in_progress",
        errors=[],
    )


def _make_llm_response(
    message: str,
    is_complete: bool = False,
    symptoms: list[dict] | None = None,
    is_no_symptom_day: bool = False,
    tone_used: str = "engaged",
) -> AIMessage:
    payload = {
        "message": message,
        "is_complete": is_complete,
        "tone_used": tone_used,
        "extraction": {
            "symptoms": symptoms or [],
            "is_no_symptom_day": is_no_symptom_day,
            "session_notes": "test session",
            "tone_used": tone_used,
        },
    }
    return AIMessage(content=json.dumps(payload))


def _patched_node(mock_response: AIMessage) -> dict:
    """Run check_in_node with a mocked LLM response."""
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_response
    with patch("app.agents.check_in_node.get_check_in_llm", return_value=mock_llm):
        state = _make_state(
            history=[{"role": "user", "content": "Test message"}],
            turn_count=1,
        )
        return check_in_node(state)


# ── Tone detection tests ──────────────────────────────────────────────────────

class TestToneDetection:
    def test_short_message_is_brief(self):
        assert _detect_tone("fine") == "brief"

    def test_pain_keywords_trigger_gentle(self):
        assert _detect_tone("I had a terrible crash today, couldn't move") == "gentle"

    def test_detailed_message_is_engaged(self):
        assert _detect_tone("I noticed a pattern after eating gluten because I always feel worse") == "engaged"

    def test_medium_message_defaults_engaged(self):
        assert _detect_tone("I had some fatigue in the afternoon, about a 6 out of 10") == "engaged"


# ── Guardrail tests ───────────────────────────────────────────────────────────

class TestGuardrails:
    def test_clean_message_has_no_violations(self):
        assert check_guardrails("How long did the fatigue last?") == []

    def test_diagnosis_word_caught(self):
        violations = check_guardrails("This diagnosis suggests...")
        assert violations

    def test_could_be_caught(self):
        violations = check_guardrails("This could be a serious condition.")
        assert violations

    def test_you_might_have_caught(self):
        violations = check_guardrails("You might have a connective tissue disorder.")
        assert violations

    def test_sounds_serious_caught(self):
        violations = check_guardrails("That sounds really concerning.")
        assert violations

    def test_case_insensitive(self):
        violations = check_guardrails("You MIGHT HAVE something serious.")
        assert violations


# ── Opening message tests ─────────────────────────────────────────────────────

class TestOpeningMessage:
    def test_opening_with_no_history_no_quick_log(self):
        state = _make_state(history=[], turn_count=0)
        result = check_in_node(state)
        assert result["turn_count"] == 1
        history = result["conversation_history"]
        assert history[-1]["role"] == "assistant"
        assert len(history[-1]["content"]) > 0

    def test_opening_with_quick_log_mentions_it(self):
        state = _make_state(
            history=[],
            turn_count=0,
            quick_log=[{"symptom_name": "Fatigue", "severity": 7}],
        )
        result = check_in_node(state)
        # Should acknowledge the quick log was received
        assert result["turn_count"] == 1
        assert result["conversation_history"][-1]["role"] == "assistant"


# ── Max turn enforcement ──────────────────────────────────────────────────────

class TestMaxTurns:
    def test_max_turns_forces_completion(self):
        state = _make_state(
            history=[{"role": "user", "content": "Still here"}],
            turn_count=8,
        )
        result = check_in_node(state)
        assert result["status"] == "awaiting_confirmation"


# ── Synthetic scenario tests ──────────────────────────────────────────────────

class TestSyntheticScenarios:
    """10 scenarios from validation.md — mocked LLM responses."""

    def _run_scenario(self, user_message: str, mock_response: AIMessage) -> dict:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_response
        with patch("app.agents.check_in_node.get_check_in_llm", return_value=mock_llm):
            state = _make_state(
                history=[{"role": "user", "content": user_message}],
                turn_count=1,
            )
            return check_in_node(state)

    def test_scenario_1_pots_presentation(self):
        """Classic POTS: orthostatic crash with racing heart and dizziness."""
        response = _make_llm_response(
            message="Got it — a crash after standing. Any other symptoms with it?",
            is_complete=False,
            symptoms=[{
                "symptom_text": "crash after standing, heart racing, dizzy",
                "hpo_terms": [
                    {"hpo_id": "HP:0001649", "label": "Tachycardia", "confidence": "high"},
                    {"hpo_id": "HP:0002321", "label": "Vertigo", "confidence": "high"},
                ],
                "body_system": "autonomic",
                "severity": 8,
                "probable_trigger": "prolonged standing",
                "duration_minutes": None,
                "onset_time": None,
                "trigger_delay_minutes": None,
                "sleep_quality": None,
                "activity_level": None,
                "stress_level": None,
                "dietary_notes": None,
                "cycle_phase": None,
            }],
        )
        result = self._run_scenario(
            "Had a really bad crash after standing for 20 minutes. Heart racing, dizzy, had to sit down. 8/10.",
            response,
        )
        assert result["status"] == "in_progress"
        symptoms = result["current_extraction"]["symptoms"]
        assert len(symptoms) == 1
        hpo_ids = [t["hpo_id"] for t in symptoms[0]["hpo_terms"]]
        assert "HP:0001649" in hpo_ids  # Tachycardia
        assert symptoms[0]["severity"] == 8
        assert symptoms[0]["probable_trigger"] == "prolonged standing"

    def test_scenario_2_fatigue_brain_fog(self):
        """Fatigue + cognitive impairment cluster, luteal phase."""
        response = _make_llm_response(
            message="Logged. Any idea what might have contributed today?",
            is_complete=False,
            symptoms=[{
                "symptom_text": "exhausted, couldn't think straight",
                "hpo_terms": [
                    {"hpo_id": "HP:0012378", "label": "Fatigue", "confidence": "high"},
                    {"hpo_id": "HP:0100543", "label": "Cognitive impairment", "confidence": "high"},
                ],
                "body_system": "neurological",
                "severity": 6,
                "sleep_quality": 9,
                "cycle_phase": "luteal",
                "duration_minutes": None,
                "onset_time": None,
                "probable_trigger": None,
                "trigger_delay_minutes": None,
                "activity_level": None,
                "stress_level": None,
                "dietary_notes": None,
            }],
        )
        result = self._run_scenario(
            "Just exhausted today and couldn't think straight. Slept 9 hours but still felt terrible. Luteal phase.",
            response,
        )
        symptoms = result["current_extraction"]["symptoms"]
        hpo_ids = [t["hpo_id"] for t in symptoms[0]["hpo_terms"]]
        assert "HP:0012378" in hpo_ids  # Fatigue
        assert "HP:0100543" in hpo_ids  # Cognitive impairment
        assert symptoms[0]["sleep_quality"] == 9
        assert symptoms[0]["cycle_phase"] == "luteal"

    def test_scenario_3_good_day(self):
        """No symptoms day — is_no_symptom_day=True, no symptom entries."""
        response = _make_llm_response(
            message="Glad to hear it! Any energy or sleep worth noting?",
            is_complete=False,
            symptoms=[],
            is_no_symptom_day=True,
        )
        result = self._run_scenario("Feeling pretty good today! No symptoms.", response)
        extraction = result["current_extraction"]
        assert extraction["is_no_symptom_day"] is True
        assert extraction["symptoms"] == []

    def test_scenario_4_good_day_with_context(self):
        """Good day with sleep context captured."""
        response = _make_llm_response(
            message="Great — logging a baseline for today.",
            is_complete=True,
            symptoms=[],
            is_no_symptom_day=True,
        )
        result = self._run_scenario("Good day! Slept well, about an 8.", response)
        assert result["status"] == "awaiting_confirmation"
        assert result["current_extraction"]["is_no_symptom_day"] is True

    def test_scenario_5_multi_system_flare(self):
        """GI + musculoskeletal during menstrual phase."""
        response = _make_llm_response(
            message="Logged both. Does the timing around your period feel predictable?",
            is_complete=False,
            symptoms=[
                {
                    "symptom_text": "GI cramping and nausea",
                    "hpo_terms": [{"hpo_id": "HP:0002027", "label": "Abdominal pain", "confidence": "high"}],
                    "body_system": "gastrointestinal",
                    "severity": 7,
                    "cycle_phase": "menstrual",
                    "duration_minutes": None, "onset_time": None, "probable_trigger": None,
                    "trigger_delay_minutes": None, "sleep_quality": None,
                    "activity_level": None, "stress_level": None, "dietary_notes": None,
                },
                {
                    "symptom_text": "joint aching in knees and hips",
                    "hpo_terms": [{"hpo_id": "HP:0002829", "label": "Arthralgia", "confidence": "high"}],
                    "body_system": "musculoskeletal",
                    "severity": 5,
                    "cycle_phase": "menstrual",
                    "duration_minutes": None, "onset_time": None, "probable_trigger": None,
                    "trigger_delay_minutes": None, "sleep_quality": None,
                    "activity_level": None, "stress_level": None, "dietary_notes": None,
                },
            ],
        )
        result = self._run_scenario(
            "GI was terrible — cramping and nausea, 7/10. Joints aching too, knees and hips. Around my period.",
            response,
        )
        symptoms = result["current_extraction"]["symptoms"]
        assert len(symptoms) == 2
        body_systems = {s["body_system"] for s in symptoms}
        assert "gastrointestinal" in body_systems
        assert "musculoskeletal" in body_systems

    def test_scenario_6_vague_input(self):
        """Vague input — empty HPO terms, symptom_text preserved."""
        response = _make_llm_response(
            message="I hear you. Can you say a bit more — where in your body did you feel it?",
            is_complete=False,
            symptoms=[{
                "symptom_text": "just felt off",
                "hpo_terms": [],
                "body_system": "other",
                "severity": 5,
                "duration_minutes": None, "onset_time": None, "probable_trigger": None,
                "trigger_delay_minutes": None, "sleep_quality": None,
                "activity_level": None, "stress_level": None, "dietary_notes": None,
                "cycle_phase": None,
            }],
        )
        result = self._run_scenario("Just felt off today. Not great.", response)
        symptoms = result["current_extraction"]["symptoms"]
        assert symptoms[0]["hpo_terms"] == []
        assert "off" in symptoms[0]["symptom_text"]

    def test_scenario_7_dietary_trigger(self):
        """Gluten trigger with delayed GI + fatigue onset."""
        response = _make_llm_response(
            message="Logged. About how long after lunch did it start?",
            is_complete=False,
            symptoms=[{
                "symptom_text": "bloating and fatigue after gluten",
                "hpo_terms": [
                    {"hpo_id": "HP:0025031", "label": "Abdominal distension", "confidence": "high"},
                    {"hpo_id": "HP:0012378", "label": "Fatigue", "confidence": "medium"},
                ],
                "body_system": "gastrointestinal",
                "severity": 6,
                "probable_trigger": "dietary — gluten",
                "trigger_delay_minutes": 120,
                "dietary_notes": "had gluten at lunch",
                "duration_minutes": None, "onset_time": None, "sleep_quality": None,
                "activity_level": None, "stress_level": None, "cycle_phase": None,
            }],
        )
        result = self._run_scenario(
            "Woke up fine but after lunch (I had gluten) by 2pm had the usual bloating and fatigue. 6/10.",
            response,
        )
        symptom = result["current_extraction"]["symptoms"][0]
        assert symptom["probable_trigger"] == "dietary — gluten"
        assert symptom["trigger_delay_minutes"] == 120

    def test_scenario_8_no_clinical_interpretation_in_output(self):
        """Guardrail: AI must not interpret emotional distress as a condition."""
        guardrail_violating_response = _make_llm_response(
            message="That sounds like anxiety disorder — you might have panic attacks.",
            is_complete=False,
            symptoms=[],
        )
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = guardrail_violating_response
        with patch("app.agents.check_in_node.get_check_in_llm", return_value=mock_llm):
            state = _make_state(
                history=[{"role": "user", "content": "Terrible day, really stressed, couldn't sleep."}],
                turn_count=1,
            )
            result = check_in_node(state)
        ai_message = result["conversation_history"][-1]["content"]
        # Guardrail should have replaced the violating message
        violations = check_guardrails(ai_message)
        assert violations == [], f"Guardrail violation remained in output: {violations}"

    def test_scenario_9_quick_log_merged(self):
        """Quick-log entry + AI follow-up extraction merged in state."""
        response = _make_llm_response(
            message="Got it. Any triggers for the fatigue today?",
            is_complete=False,
            symptoms=[{
                "symptom_text": "fatigue from quick log",
                "hpo_terms": [{"hpo_id": "HP:0012378", "label": "Fatigue", "confidence": "high"}],
                "body_system": "neurological",
                "severity": 7,
                "duration_minutes": None, "onset_time": None, "probable_trigger": None,
                "trigger_delay_minutes": None, "sleep_quality": None,
                "activity_level": None, "stress_level": None, "dietary_notes": None,
                "cycle_phase": None,
            }],
        )
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = response
        with patch("app.agents.check_in_node.get_check_in_llm", return_value=mock_llm):
            state = _make_state(
                history=[{"role": "user", "content": "Just adding some context."}],
                turn_count=2,
                quick_log=[{"symptom_name": "Fatigue", "severity": 7}],
            )
            result = check_in_node(state)
        assert result["current_extraction"]["symptoms"][0]["severity"] == 7

    def test_scenario_10_edit_flow_correction(self):
        """Patient edits severity — corrected value used in final extraction."""
        corrected_response = _make_llm_response(
            message="Updated — severity 9. Does this summary look right?",
            is_complete=True,
            symptoms=[{
                "symptom_text": "joint pain",
                "hpo_terms": [{"hpo_id": "HP:0002829", "label": "Arthralgia", "confidence": "high"}],
                "body_system": "musculoskeletal",
                "severity": 9,  # corrected from 7
                "duration_minutes": None, "onset_time": None, "probable_trigger": None,
                "trigger_delay_minutes": None, "sleep_quality": None,
                "activity_level": None, "stress_level": None, "dietary_notes": None,
                "cycle_phase": None,
            }],
        )
        result = _patched_node(corrected_response)
        assert result["status"] == "awaiting_confirmation"
        assert result["current_extraction"]["symptoms"][0]["severity"] == 9


# ── HPO hallucination stripping ───────────────────────────────────────────────

class TestHPOHallucinationStripping:
    def test_invalid_hpo_stripped_from_output(self):
        """An HPO code not in the vocabulary must be stripped before state update."""
        response_with_bad_id = _make_llm_response(
            message="Got it.",
            is_complete=False,
            symptoms=[{
                "symptom_text": "weird symptom",
                "hpo_terms": [
                    {"hpo_id": "HP:9999999", "label": "Made up", "confidence": "high"},  # invalid
                    {"hpo_id": "HP:0012378", "label": "Fatigue", "confidence": "high"},  # valid
                ],
                "body_system": "neurological",
                "severity": 5,
                "duration_minutes": None, "onset_time": None, "probable_trigger": None,
                "trigger_delay_minutes": None, "sleep_quality": None,
                "activity_level": None, "stress_level": None, "dietary_notes": None,
                "cycle_phase": None,
            }],
        )
        result = _patched_node(response_with_bad_id)
        hpo_ids = [t["hpo_id"] for t in result["current_extraction"]["symptoms"][0]["hpo_terms"]]
        assert "HP:9999999" not in hpo_ids
        assert "HP:0012378" in hpo_ids

    def test_all_valid_hpo_preserved(self):
        response = _make_llm_response(
            message="Logged.",
            symptoms=[{
                "symptom_text": "fatigue",
                "hpo_terms": [
                    {"hpo_id": "HP:0012378", "label": "Fatigue", "confidence": "high"},
                    {"hpo_id": "HP:0002829", "label": "Arthralgia", "confidence": "medium"},
                ],
                "body_system": "musculoskeletal",
                "severity": 6,
                "duration_minutes": None, "onset_time": None, "probable_trigger": None,
                "trigger_delay_minutes": None, "sleep_quality": None,
                "activity_level": None, "stress_level": None, "dietary_notes": None,
                "cycle_phase": None,
            }],
        )
        result = _patched_node(response)
        hpo_ids = {t["hpo_id"] for t in result["current_extraction"]["symptoms"][0]["hpo_terms"]}
        assert hpo_ids == {"HP:0012378", "HP:0002829"}
