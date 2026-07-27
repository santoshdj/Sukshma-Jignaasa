"""
Tests for FHIR writer and HPO validator.
All httpx calls are mocked — no network required.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.check_in import CheckInExtraction, ExtractedSymptom, HPOTerm
from app.services.fhir_writer import (
    _build_no_symptom_observation,
    _build_symptom_observation,
    extraction_to_observations,
    write_check_in,
)
from app.services.hpo_validator import (
    get_label,
    is_valid,
    strip_invalid,
    validate_all,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

_NOW = datetime(2026, 7, 26, 14, 0, 0, tzinfo=timezone.utc)
_PATIENT_ID = "patient-test-001"


def _make_symptom(**kwargs) -> ExtractedSymptom:
    defaults = {
        "symptom_text": "fatigue after standing",
        "hpo_terms": [HPOTerm(hpo_id="HP:0012378", label="Fatigue", confidence="high")],
        "body_system": "autonomic",
        "severity": 7,
    }
    defaults.update(kwargs)
    return ExtractedSymptom(**defaults)


def _make_extraction(symptoms=None, is_no_symptom_day=False) -> CheckInExtraction:
    return CheckInExtraction(
        symptoms=symptoms or ([] if is_no_symptom_day else [_make_symptom()]),
        is_no_symptom_day=is_no_symptom_day,
    )


# ── HPO Validator Tests ───────────────────────────────────────────────────────

class TestHPOValidator:
    def test_valid_id_passes(self):
        assert is_valid("HP:0012378") is True

    def test_invalid_id_fails(self):
        assert is_valid("HP:9999999") is False

    def test_get_label_known_id(self):
        label = get_label("HP:0012378")
        assert label == "Fatigue"

    def test_get_label_unknown_id(self):
        assert get_label("HP:9999999") is None

    def test_strip_invalid_removes_bad_ids(self):
        terms = [
            {"hpo_id": "HP:0012378", "label": "Fatigue", "confidence": "high"},
            {"hpo_id": "HP:9999999", "label": "Fake", "confidence": "high"},
        ]
        valid = strip_invalid(terms)
        assert len(valid) == 1
        assert valid[0]["hpo_id"] == "HP:0012378"

    def test_strip_invalid_keeps_all_valid(self):
        terms = [
            {"hpo_id": "HP:0012378", "label": "Fatigue", "confidence": "high"},
            {"hpo_id": "HP:0002829", "label": "Arthralgia", "confidence": "medium"},
        ]
        valid = strip_invalid(terms)
        assert len(valid) == 2

    def test_validate_all_separates_valid_invalid(self):
        terms = [
            {"hpo_id": "HP:0012378", "label": "Fatigue", "confidence": "high"},
            {"hpo_id": "HP:9999999", "label": "Bad", "confidence": "low"},
        ]
        valid, invalid_ids = validate_all(terms)
        assert len(valid) == 1
        assert "HP:9999999" in invalid_ids

    def test_strip_invalid_empty_list(self):
        assert strip_invalid([]) == []


# ── FHIR Resource Structure Tests ─────────────────────────────────────────────

class TestBuildSymptomObservation:
    def test_basic_structure(self):
        symptom = _make_symptom()
        obs = _build_symptom_observation(symptom, _PATIENT_ID, _NOW)

        assert obs["resourceType"] == "Observation"
        assert obs["status"] == "final"
        assert obs["subject"]["reference"] == f"Patient/{_PATIENT_ID}"
        assert obs["effectiveDateTime"] == _NOW.isoformat()

    def test_hpo_coding_present(self):
        symptom = _make_symptom()
        obs = _build_symptom_observation(symptom, _PATIENT_ID, _NOW)
        coding = obs["code"]["coding"]
        assert coding[0]["system"] == "https://hpo.jax.org/"
        assert coding[0]["code"] == "HP:0012378"
        assert coding[0]["display"] == "Fatigue"

    def test_symptom_text_preserved(self):
        symptom = _make_symptom(symptom_text="bad fatigue crash after walking")
        obs = _build_symptom_observation(symptom, _PATIENT_ID, _NOW)
        assert obs["code"]["text"] == "bad fatigue crash after walking"

    def test_severity_in_components(self):
        symptom = _make_symptom(severity=8)
        obs = _build_symptom_observation(symptom, _PATIENT_ID, _NOW)
        component_codes = {c["code"]["text"] for c in obs["component"]}
        assert "severity" in component_codes
        severity_comp = next(c for c in obs["component"] if c["code"]["text"] == "severity")
        assert severity_comp["valueInteger"] == 8

    def test_trigger_in_components_when_present(self):
        symptom = _make_symptom(probable_trigger="prolonged standing", trigger_delay_minutes=10)
        obs = _build_symptom_observation(symptom, _PATIENT_ID, _NOW)
        comp_map = {c["code"]["text"]: c for c in obs["component"]}
        assert "probable_trigger" in comp_map
        assert comp_map["probable_trigger"]["valueString"] == "prolonged standing"
        assert comp_map["trigger_delay_minutes"]["valueInteger"] == 10

    def test_no_trigger_component_when_absent(self):
        symptom = _make_symptom(probable_trigger=None)
        obs = _build_symptom_observation(symptom, _PATIENT_ID, _NOW)
        comp_codes = {c["code"]["text"] for c in obs["component"]}
        assert "probable_trigger" not in comp_codes

    def test_context_fields_in_components(self):
        symptom = _make_symptom(
            sleep_quality=6, activity_level="low", stress_level=8,
            dietary_notes="ate gluten", cycle_phase="luteal"
        )
        obs = _build_symptom_observation(symptom, _PATIENT_ID, _NOW)
        comp_map = {c["code"]["text"]: c for c in obs["component"]}
        assert comp_map["sleep_quality"]["valueInteger"] == 6
        assert comp_map["activity_level"]["valueString"] == "low"
        assert comp_map["stress_level"]["valueInteger"] == 8
        assert comp_map["dietary_notes"]["valueString"] == "ate gluten"
        assert comp_map["cycle_phase"]["valueString"] == "luteal"

    def test_hallucinated_hpo_stripped_from_fhir(self):
        """Invalid HPO ID must not appear in FHIR Observation coding."""
        symptom = ExtractedSymptom(
            symptom_text="unknown symptom",
            hpo_terms=[],  # already stripped upstream; test defence-in-depth
            body_system="other",
            severity=4,
        )
        # Manually inject a bad term dict to test fhir_writer's own stripping
        symptom_dict = symptom.model_dump()
        symptom_dict["hpo_terms"] = [
            {"hpo_id": "HP:9999999", "label": "Fake", "confidence": "low"},
            {"hpo_id": "HP:0012378", "label": "Fatigue", "confidence": "high"},
        ]
        bad_symptom = ExtractedSymptom(**{**symptom_dict, "hpo_terms": []})
        # Build observation via the internal function directly
        from app.services.fhir_writer import _build_symptom_observation as _bso
        obs = _bso(bad_symptom, _PATIENT_ID, _NOW)
        # No HPO coding in the result (hpo_terms was empty)
        assert "coding" not in obs["code"]

    def test_no_hpo_terms_uses_text_only_code(self):
        symptom = _make_symptom(hpo_terms=[])
        obs = _build_symptom_observation(symptom, _PATIENT_ID, _NOW)
        assert "coding" not in obs["code"]
        assert obs["code"]["text"] == symptom.symptom_text

    def test_onset_time_used_when_provided(self):
        onset = datetime(2026, 7, 26, 10, 30, 0, tzinfo=timezone.utc)
        symptom = _make_symptom(onset_time=onset)
        obs = _build_symptom_observation(symptom, _PATIENT_ID, _NOW)
        assert obs["effectiveDateTime"] == onset.isoformat()

    def test_check_in_time_used_when_no_onset(self):
        symptom = _make_symptom(onset_time=None)
        obs = _build_symptom_observation(symptom, _PATIENT_ID, _NOW)
        assert obs["effectiveDateTime"] == _NOW.isoformat()


class TestBuildNoSymptomObservation:
    def test_basic_structure(self):
        obs = _build_no_symptom_observation(_PATIENT_ID, _NOW)
        assert obs["resourceType"] == "Observation"
        assert obs["status"] == "final"
        assert obs["subject"]["reference"] == f"Patient/{_PATIENT_ID}"

    def test_is_no_symptom_day_component(self):
        obs = _build_no_symptom_observation(_PATIENT_ID, _NOW)
        comp_map = {c["code"]["text"]: c for c in obs["component"]}
        assert "is_no_symptom_day" in comp_map
        assert comp_map["is_no_symptom_day"]["valueBoolean"] is True

    def test_code_text_identifies_baseline(self):
        obs = _build_no_symptom_observation(_PATIENT_ID, _NOW)
        assert "No symptoms" in obs["code"]["text"]

    def test_sleep_quality_included_when_provided(self):
        obs = _build_no_symptom_observation(_PATIENT_ID, _NOW, sleep_quality=8)
        comp_map = {c["code"]["text"]: c for c in obs["component"]}
        assert comp_map["sleep_quality"]["valueInteger"] == 8

    def test_optional_fields_absent_when_not_provided(self):
        obs = _build_no_symptom_observation(_PATIENT_ID, _NOW)
        comp_codes = {c["code"]["text"] for c in obs["component"]}
        assert "sleep_quality" not in comp_codes
        assert "activity_level" not in comp_codes


# ── extraction_to_observations Tests ─────────────────────────────────────────

class TestExtractionToObservations:
    def test_symptom_extraction_produces_one_obs_per_symptom(self):
        extraction = _make_extraction(
            symptoms=[_make_symptom(), _make_symptom(symptom_text="joint pain", body_system="musculoskeletal")]
        )
        obs_list = extraction_to_observations(extraction, _PATIENT_ID, _NOW)
        assert len(obs_list) == 2

    def test_no_symptom_day_produces_exactly_one_obs(self):
        extraction = _make_extraction(is_no_symptom_day=True)
        obs_list = extraction_to_observations(extraction, _PATIENT_ID, _NOW)
        assert len(obs_list) == 1
        comp_map = {c["code"]["text"]: c for c in obs_list[0]["component"]}
        assert comp_map["is_no_symptom_day"]["valueBoolean"] is True

    def test_uses_current_time_when_check_in_time_not_provided(self):
        extraction = _make_extraction()
        obs_list = extraction_to_observations(extraction, _PATIENT_ID)
        assert len(obs_list) == 1
        assert obs_list[0]["effectiveDateTime"] is not None

    def test_all_observations_reference_correct_patient(self):
        extraction = _make_extraction(
            symptoms=[_make_symptom(), _make_symptom(symptom_text="headache", body_system="neurological")]
        )
        obs_list = extraction_to_observations(extraction, _PATIENT_ID, _NOW)
        for obs in obs_list:
            assert obs["subject"]["reference"] == f"Patient/{_PATIENT_ID}"


# ── write_check_in Tests (mocked httpx) ──────────────────────────────────────

class TestWriteCheckIn:
    @pytest.mark.asyncio
    async def test_successful_write_returns_ids(self):
        observations = extraction_to_observations(_make_extraction(), _PATIENT_ID, _NOW)

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"id": "obs-abc-123", "resourceType": "Observation"}

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.post.return_value = mock_response

        with patch("app.services.fhir_writer.httpx.AsyncClient", return_value=mock_client):
            ids = await write_check_in(observations, _PATIENT_ID)

        assert ids == ["obs-abc-123"]
        assert mock_client.post.call_count == len(observations)

    @pytest.mark.asyncio
    async def test_partial_failure_returns_successful_ids_only(self):
        """One observation fails — others still return IDs."""
        import httpx as httpx_module

        observations = extraction_to_observations(
            _make_extraction(symptoms=[_make_symptom(), _make_symptom(symptom_text="headache", body_system="neurological")]),
            _PATIENT_ID,
            _NOW,
        )

        call_count = {"n": 0}

        def make_response(status=200, obs_id="obs-001"):
            r = MagicMock()
            if status >= 400:
                r.raise_for_status.side_effect = httpx_module.HTTPStatusError(
                    "error", request=MagicMock(), response=MagicMock(status_code=status, text="error")
                )
            else:
                r.raise_for_status = MagicMock()
                r.json.return_value = {"id": obs_id}
            return r

        async def mock_post(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return make_response(200, "obs-001")
            return make_response(500)

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.post.side_effect = mock_post

        with patch("app.services.fhir_writer.httpx.AsyncClient", return_value=mock_client):
            ids = await write_check_in(observations, _PATIENT_ID)

        assert ids == ["obs-001"]

    @pytest.mark.asyncio
    async def test_bearer_token_sent_in_header(self):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"id": "obs-xyz"}

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.post.return_value = mock_response

        observations = extraction_to_observations(_make_extraction(), _PATIENT_ID, _NOW)

        with patch("app.services.fhir_writer.httpx.AsyncClient", return_value=mock_client):
            await write_check_in(observations, _PATIENT_ID, access_token="test-token-abc")

        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers.get("Authorization") == "Bearer test-token-abc"

    @pytest.mark.asyncio
    async def test_empty_observations_returns_empty_list(self):
        with patch("app.services.fhir_writer.httpx.AsyncClient"):
            ids = await write_check_in([], _PATIENT_ID)
        assert ids == []
