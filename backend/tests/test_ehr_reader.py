"""
Tests for EHR reader service — all Medblocks API calls mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from app.services.ehr_reader import (
    start_patient_session,
    verify_patient_session,
    get_connections,
    pull_fhir_records,
    _active_connection_status,
)


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data
    mock.raise_for_status = MagicMock() if status_code < 400 else MagicMock(
        side_effect=httpx.HTTPStatusError("error", request=MagicMock(), response=MagicMock(status_code=status_code, text="error"))
    )
    return mock


class TestStartPatientSession:
    @pytest.mark.asyncio
    async def test_returns_auth_url(self):
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.post.return_value = _mock_response({"url": "https://medblocks.com/auth?session=abc"})

        with patch("app.services.ehr_reader.httpx.AsyncClient", return_value=mock_client):
            result = await start_patient_session("patient-001", "https://myapp.com/return")

        assert result == "https://medblocks.com/auth?session=abc"

    @pytest.mark.asyncio
    async def test_raises_if_no_auth_url_in_response(self):
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.post.return_value = _mock_response({"id": "session-123"})

        with patch("app.services.ehr_reader.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ValueError, match="auth_url"):
                await start_patient_session("patient-001", "https://myapp.com/return")


class TestVerifyPatientSession:
    @pytest.mark.asyncio
    async def test_returns_session_dict(self):
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.get.return_value = _mock_response({"id": "sess-001", "status": "completed", "patient_id": "pat-001"})

        with patch("app.services.ehr_reader.httpx.AsyncClient", return_value=mock_client):
            result = await verify_patient_session("sess-001")

        assert result["id"] == "sess-001"


class TestGetConnections:
    @pytest.mark.asyncio
    async def test_returns_connections_list(self):
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.get.return_value = _mock_response({
            "id": "pat-001",
            "connections": [{"id": "conn-1", "status": "active"}]
        })

        with patch("app.services.ehr_reader.httpx.AsyncClient", return_value=mock_client):
            result = await get_connections("pat-001")

        assert result == [{"id": "conn-1", "status": "active"}]

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_connections(self):
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.get.return_value = _mock_response({"id": "pat-001"})

        with patch("app.services.ehr_reader.httpx.AsyncClient", return_value=mock_client):
            result = await get_connections("pat-001")

        assert result == []


class TestActiveConnectionStatus:
    def test_active_when_any_active(self):
        assert _active_connection_status([{"status": "active"}]) == "active"

    def test_pending_when_pending_and_no_active(self):
        assert _active_connection_status([{"status": "pending"}]) == "pending"

    def test_failed_when_only_failed(self):
        assert _active_connection_status([{"status": "failed"}]) == "failed"

    def test_not_connected_when_empty(self):
        assert _active_connection_status([]) == "not_connected"

    def test_active_takes_precedence_over_pending(self):
        assert _active_connection_status([{"status": "pending"}, {"status": "active"}]) == "active"


class TestPullFHIRRecords:
    @pytest.mark.asyncio
    async def test_returns_records_grouped_by_type(self):
        condition_resource = {"resourceType": "Condition", "id": "cond-001"}
        page_response = {"data": [{"resource": condition_resource}], "has_more": False}

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.get.return_value = _mock_response(page_response)

        with patch("app.services.ehr_reader.httpx.AsyncClient", return_value=mock_client):
            result = await pull_fhir_records("pat-001", resource_types=["Condition"])

        assert "Condition" in result
        assert len(result["Condition"]) == 1

    @pytest.mark.asyncio
    async def test_handles_empty_records(self):
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.get.return_value = _mock_response({"data": [], "has_more": False})

        with patch("app.services.ehr_reader.httpx.AsyncClient", return_value=mock_client):
            result = await pull_fhir_records("pat-001", resource_types=["Observation"])

        assert result["Observation"] == []

    @pytest.mark.asyncio
    async def test_paginates_when_has_more(self):
        call_count = {"n": 0}
        resources_page_1 = [{"resource": {"resourceType": "Observation", "id": "obs-001"}}]
        resources_page_2 = [{"resource": {"resourceType": "Observation", "id": "obs-002"}}]

        def make_response(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _mock_response({"data": resources_page_1, "has_more": True, "next_cursor": "cursor-1"})
            return _mock_response({"data": resources_page_2, "has_more": False})

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_client.get.side_effect = make_response

        with patch("app.services.ehr_reader.httpx.AsyncClient", return_value=mock_client):
            result = await pull_fhir_records("pat-001", resource_types=["Observation"])

        assert len(result["Observation"]) == 2
        assert call_count["n"] == 2  # two pages fetched


class TestHypothesisModels:
    """Ensure guardrail enforcement in Pydantic models."""

    def test_discuss_with_specialist_always_true(self):
        from app.models.hypothesis import HypothesisProfile
        profile = HypothesisProfile(
            condition_id="POTS",
            condition_name="POTS",
            match_strength="high",
            matching_symptoms=[],
            missing_signals=[],
            plain_language_explanation="test",
            specialist_type="neurologist",
            confidence_note="Pattern similarity is uncertain and not diagnostic.",
            discuss_with_specialist=False,  # LLM set this to False — should be overridden
        )
        assert profile.discuss_with_specialist is True

    def test_guardrail_disclosure_always_canonical(self):
        from app.models.hypothesis import HypothesisReport
        report = HypothesisReport(
            patient_id="p1",
            observation_count=35,
            hypotheses=[],
            summary="test summary",
            guardrail_disclosure="CUSTOM TEXT FROM LLM",  # Should be overridden
        )
        assert "medical diagnosis" in report.guardrail_disclosure
        assert "CUSTOM TEXT FROM LLM" not in report.guardrail_disclosure
