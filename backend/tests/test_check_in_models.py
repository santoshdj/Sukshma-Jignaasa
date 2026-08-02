"""
Unit tests for check-in Pydantic models.
Tests cover: model validation, HPO vocabulary enforcement, guardrail invariants.
Run: uv run pytest tests/test_check_in_models.py -v
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.check_in import (
    CheckInExtraction,
    ConfirmCheckInRequest,
    ConfirmationSummary,
    ExtractedSymptom,
    HPOTerm,
    QuickLogEntry,
    StartCheckInRequest,
    VALID_HPO_IDS,
)


# ── HPO Term Tests ────────────────────────────────────────────────────────────

class TestHPOTerm:
    def test_valid_hpo_id_accepted(self):
        """A known vocabulary HPO ID must be accepted."""
        term = HPOTerm(hpo_id="HP:0012378", label="Fatigue", confidence="high")
        assert term.hpo_id == "HP:0012378"

    def test_invalid_hpo_id_rejected(self):
        """An HPO ID not in the curated vocabulary must be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            HPOTerm(hpo_id="HP:9999999", label="Fake symptom", confidence="high")
        assert "not in the curated vocabulary" in str(exc_info.value)

    def test_malformed_hpo_id_rejected(self):
        """An ID that doesn't match HP:XXXXXXX pattern must be rejected."""
        with pytest.raises(ValidationError):
            HPOTerm(hpo_id="OMIM:123456", label="Something", confidence="low")

    def test_invalid_confidence_rejected(self):
        """Confidence must be one of high / medium / low."""
        with pytest.raises(ValidationError):
            HPOTerm(hpo_id="HP:0012378", label="Fatigue", confidence="maybe")  # type: ignore

    def test_empty_label_rejected(self):
        with pytest.raises(ValidationError):
            HPOTerm(hpo_id="HP:0012378", label="", confidence="high")

    def test_all_vocabulary_ids_pass_validation(self):
        """Every ID in hpo_terms.json must pass HPOTerm validation."""
        vocab_path = Path(__file__).resolve().parents[1] / "app" / "data" / "hpo_terms.json"
        with vocab_path.open("r") as f:
            terms = json.load(f)
        for entry in terms:
            term = HPOTerm(hpo_id=entry["hpo_id"], label=entry["label"], confidence="high")
            assert term.hpo_id == entry["hpo_id"]


# ── ExtractedSymptom Tests ────────────────────────────────────────────────────

class TestExtractedSymptom:
    def _valid_symptom(self, **overrides) -> dict:
        base = {
            "symptom_text": "Really bad fatigue after standing at the supermarket",
            "hpo_terms": [{"hpo_id": "HP:0012378", "label": "Fatigue", "confidence": "high"}],
            "body_system": "autonomic",
            "severity": 8,
        }
        return {**base, **overrides}

    def test_valid_symptom_accepted(self):
        s = ExtractedSymptom(**self._valid_symptom())
        assert s.severity == 8
        assert s.hpo_terms[0].hpo_id == "HP:0012378"

    def test_severity_below_range_rejected(self):
        with pytest.raises(ValidationError):
            ExtractedSymptom(**self._valid_symptom(severity=0))

    def test_severity_above_range_rejected(self):
        with pytest.raises(ValidationError):
            ExtractedSymptom(**self._valid_symptom(severity=11))

    def test_invalid_body_system_rejected(self):
        with pytest.raises(ValidationError):
            ExtractedSymptom(**self._valid_symptom(body_system="cosmic"))  # type: ignore

    def test_empty_symptom_text_rejected(self):
        with pytest.raises(ValidationError):
            ExtractedSymptom(**self._valid_symptom(symptom_text=""))

    def test_negative_duration_rejected(self):
        with pytest.raises(ValidationError):
            ExtractedSymptom(**self._valid_symptom(duration_minutes=-1))

    def test_empty_hpo_terms_allowed(self):
        """Unknown symptoms may have no HPO mapping — that is valid."""
        s = ExtractedSymptom(**self._valid_symptom(hpo_terms=[]))
        assert s.hpo_terms == []

    def test_cycle_phase_values(self):
        for phase in ("follicular", "ovulatory", "luteal", "menstrual", "not_applicable", "unknown"):
            s = ExtractedSymptom(**self._valid_symptom(cycle_phase=phase))
            assert s.cycle_phase == phase

    def test_invalid_cycle_phase_rejected(self):
        with pytest.raises(ValidationError):
            ExtractedSymptom(**self._valid_symptom(cycle_phase="new_moon"))  # type: ignore

    def test_activity_level_values(self):
        for level in ("low", "moderate", "high"):
            s = ExtractedSymptom(**self._valid_symptom(activity_level=level))
            assert s.activity_level == level

    def test_hallucinated_hpo_id_in_symptom_rejected(self):
        """HPO ID not in vocabulary embedded in a symptom must be rejected."""
        with pytest.raises(ValidationError):
            ExtractedSymptom(**self._valid_symptom(
                hpo_terms=[{"hpo_id": "HP:0000001", "label": "Root", "confidence": "low"}]
            ))

    def test_sleep_quality_out_of_range(self):
        with pytest.raises(ValidationError):
            ExtractedSymptom(**self._valid_symptom(sleep_quality=11))


# ── CheckInExtraction Tests ───────────────────────────────────────────────────

class TestCheckInExtraction:
    def _valid_extraction(self, **overrides) -> dict:
        base = {
            "symptoms": [],
            "is_no_symptom_day": False,
        }
        return {**base, **overrides}

    def test_valid_empty_symptoms_accepted(self):
        e = CheckInExtraction(**self._valid_extraction(is_no_symptom_day=True))
        assert e.is_no_symptom_day is True
        assert e.symptoms == []

    def test_no_symptom_day_with_symptoms_rejected(self):
        """Contradictory state: is_no_symptom_day=True but symptoms list non-empty."""
        with pytest.raises(ValidationError) as exc_info:
            CheckInExtraction(
                symptoms=[
                    {
                        "symptom_text": "headache",
                        "hpo_terms": [],
                        "body_system": "neurological",
                        "severity": 5,
                    }
                ],
                is_no_symptom_day=True,
            )
        assert "is_no_symptom_day is True" in str(exc_info.value)

    def test_symptom_day_with_symptoms_accepted(self):
        e = CheckInExtraction(
            symptoms=[
                {
                    "symptom_text": "fatigue after walking",
                    "hpo_terms": [{"hpo_id": "HP:0012378", "label": "Fatigue", "confidence": "high"}],
                    "body_system": "neurological",
                    "severity": 7,
                }
            ],
            is_no_symptom_day=False,
        )
        assert len(e.symptoms) == 1

    def test_tone_used_defaults(self):
        e = CheckInExtraction(**self._valid_extraction())
        assert e.tone_used == "engaged"

    def test_invalid_tone_rejected(self):
        with pytest.raises(ValidationError):
            CheckInExtraction(**self._valid_extraction(tone_used="aggressive"))  # type: ignore

    def test_session_notes_defaults_empty(self):
        e = CheckInExtraction(**self._valid_extraction())
        assert e.session_notes == ""


# ── QuickLogEntry Tests ───────────────────────────────────────────────────────

class TestQuickLogEntry:
    def test_valid_entry(self):
        e = QuickLogEntry(symptom_name="Fatigue", severity=7)
        assert e.severity == 7
        assert e.duration_minutes is None

    def test_severity_out_of_range(self):
        with pytest.raises(ValidationError):
            QuickLogEntry(symptom_name="Fatigue", severity=0)

    def test_empty_symptom_name_rejected(self):
        with pytest.raises(ValidationError):
            QuickLogEntry(symptom_name="", severity=5)


# ── API Model Tests ───────────────────────────────────────────────────────────

class TestStartCheckInRequest:
    def test_valid_request(self):
        req = StartCheckInRequest(patient_id="patient-abc-123")
        assert req.quick_log_entries == []

    def test_empty_patient_id_rejected(self):
        with pytest.raises(ValidationError):
            StartCheckInRequest(patient_id="")

    def test_with_quick_log_entries(self):
        req = StartCheckInRequest(
            patient_id="patient-abc-123",
            quick_log_entries=[{"symptom_name": "Joint pain", "severity": 6}],
        )
        assert len(req.quick_log_entries) == 1


class TestConfirmCheckInRequest:
    def test_confirm_decision(self):
        req = ConfirmCheckInRequest(session_id="sess-001", decision="confirm")
        assert req.decision == "confirm"

    def test_edit_decision_with_notes(self):
        req = ConfirmCheckInRequest(
            session_id="sess-001",
            decision="edit",
            edit_notes="Please change severity to 9",
        )
        assert req.edit_notes == "Please change severity to 9"

    def test_invalid_decision_rejected(self):
        with pytest.raises(ValidationError):
            ConfirmCheckInRequest(session_id="sess-001", decision="maybe")  # type: ignore


# ── Vocabulary Integrity Tests ────────────────────────────────────────────────

class TestHPOVocabulary:
    def test_vocabulary_not_empty(self):
        assert len(VALID_HPO_IDS) > 100

    def test_vocabulary_contains_key_rare_disease_terms(self):
        """Core rare disease phenotype terms must be in the vocabulary."""
        required = {
            "HP:0012378",  # Fatigue
            "HP:0002829",  # Arthralgia
            "HP:0001382",  # Joint hypermobility
            "HP:0001649",  # Tachycardia (POTS)
            "HP:0002907",  # Orthostatic hypotension
            "HP:0100543",  # Cognitive impairment (brain fog)
            "HP:0025031",  # Abdominal distension (bloating)
            "HP:0001025",  # Urticaria (hives — MCAS)
            "HP:0003546",  # Exercise intolerance (PEM)
        }
        missing = required - VALID_HPO_IDS
        assert not missing, f"Required HPO terms missing from vocabulary: {missing}"

    def test_all_vocabulary_ids_match_pattern(self):
        import re
        pattern = re.compile(r"^HP:\d{7}$")
        invalid = [hid for hid in VALID_HPO_IDS if not pattern.match(hid)]
        assert not invalid, f"HPO IDs with invalid format: {invalid[:5]}"
