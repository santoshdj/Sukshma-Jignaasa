"""
EHR Reader — Medblocks Patient Access integration.

All calls use httpx + the Medblocks REST API directly.
API key is kept server-side only.

Flow:
  1. start_patient_session(patient_id, return_url) → auth_url
  2. Patient authorises at Medblocks hosted page
  3. verify_patient_session(patient_session_id) → session dict
  4. get_connections(patient_id) → connection list
  5. pull_fhir_records(patient_id, resource_types) → grouped FHIR resources
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from app.utils.config import get_settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://app.medblocks.com"
_FHIR_RESOURCE_TYPES = ["Condition", "Observation", "MedicationRequest", "AllergyIntolerance", "Encounter"]
_PAGE_SIZE = 100


def _headers() -> dict[str, str]:
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.medblocks_api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def start_patient_session(patient_id: str, return_url: str) -> str:
    """
    Start a Medblocks patient session.
    Returns the auth_url to redirect the patient to.
    """
    settings = get_settings()
    key = settings.medblocks_api_key
    key_preview = f"{key[:8]}…{key[-4:]}" if len(key) > 12 else ("<empty>" if not key else "<short>")
    # TODO: REMOVE BEFORE COMMIT — full key logged for local debugging only
    logger.warning("DEBUG api_key_full=%s", key)
    logger.info(
        "start_patient_session: patient_id=%s return_url=%s api_key=%s",
        patient_id, return_url, key_preview,
    )

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{_BASE_URL}/patient-sessions",
            headers=_headers(),
            json={"patient_id": patient_id, "return_url": return_url},
        )
        logger.info(
            "start_patient_session: response status=%s url=%s",
            resp.status_code, resp.url,
        )
        if resp.status_code >= 400:
            logger.error(
                "start_patient_session: error body=%s",
                resp.text[:500],
            )
        resp.raise_for_status()
        data = resp.json()
        auth_url: str = data.get("url") or data.get("auth_url") or data.get("authorization_url", "")
        if not auth_url:
            raise ValueError(f"Medblocks did not return an auth_url: {data}")
        logger.info("start_patient_session: auth_url obtained successfully")
        return auth_url


async def verify_patient_session(patient_session_id: str) -> dict:
    """
    Retrieve and verify a patient session server-side.
    Per Medblocks skill: never trust browser query params alone.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{_BASE_URL}/patient-sessions/{patient_session_id}",
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def get_connections(patient_id: str) -> list[dict]:
    """Return the list of connections for a patient."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{_BASE_URL}/patients/{patient_id}",
            headers=_headers(),
        )
        resp.raise_for_status()
        patient = resp.json()
        return patient.get("connections", [])


def _active_connection_status(connections: list[dict]) -> str:
    """
    Determine overall status from connection list.
    Medblocks may return various statuses — be lenient about what counts as "active".
    """
    if not connections:
        return "not_connected"
    
    statuses = {c.get("status", "").lower() for c in connections}
    logger.info("Connection statuses from Medblocks: %s", statuses)
    
    # Accept multiple variations of "active" status
    active_variants = {"active", "connected", "authorized", "success", "completed"}
    if statuses & active_variants:  # intersection
        return "active"
    
    pending_variants = {"pending", "in_progress", "processing"}
    if statuses & pending_variants:
        return "pending"
    
    failed_variants = {"failed", "error", "denied", "rejected"}
    if statuses & failed_variants:
        return "failed"
    
    # Unknown status — log and default to pending rather than failed
    logger.warning("Unknown connection statuses: %s — defaulting to pending", statuses)
    return "pending"


async def pull_fhir_records(
    patient_id: str,
    resource_types: list[str] | None = None,
) -> dict[str, list[dict]]:
    """
    Paginated pull of FHIR records from Medblocks.
    Returns a dict of resource_type → list of FHIR resource dicts.

    Per Medblocks skill: preserve pagination with has_more + next_cursor.
    Records may not be available immediately after connection.
    """
    resource_types = resource_types or _FHIR_RESOURCE_TYPES
    results: dict[str, list[dict]] = {rt: [] for rt in resource_types}

    async with httpx.AsyncClient(timeout=30.0) as client:
        for resource_type in resource_types:
            starting_after: str | None = None
            page = 0

            while True:
                params: dict = {"count": _PAGE_SIZE, "resource_type": resource_type}
                if starting_after:
                    params["starting_after"] = starting_after

                try:
                    resp = await client.get(
                        f"{_BASE_URL}/patients/{patient_id}/records",
                        headers=_headers(),
                        params=params,
                    )
                    resp.raise_for_status()
                    page_data = resp.json()
                except httpx.HTTPStatusError as exc:
                    logger.error(
                        "FHIR pull HTTP error for %s/%s: %s",
                        patient_id, resource_type, exc.response.status_code,
                    )
                    break
                except Exception as exc:
                    logger.error("FHIR pull error for %s/%s: %s", patient_id, resource_type, exc)
                    break

                items: list[dict] = page_data.get("data", [])
                for item in items:
                    resource = item.get("resource") or item
                    if resource.get("resourceType") == resource_type or not resource.get("resourceType"):
                        results[resource_type].append(resource)

                page += 1
                has_more: bool = page_data.get("has_more", False)
                next_cursor: str | None = page_data.get("next_cursor")

                if not has_more or not next_cursor:
                    break
                starting_after = next_cursor

            logger.info(
                "Pulled %d %s records for patient %s",
                len(results[resource_type]), resource_type, patient_id,
            )

    return results
