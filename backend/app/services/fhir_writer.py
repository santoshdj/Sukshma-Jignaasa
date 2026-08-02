"""
FHIR Writer
-----------
Two responsibilities:
  1. extraction_to_observations() — pure function, no I/O.
     Maps a validated CheckInExtraction to a list of FHIR R4 Observation dicts.

  2. write_check_in() — I/O function.
     POSTs each Observation to the configured FHIR endpoint (Medblocks / HAPI FHIR).
     Partial success is acceptable: errors are logged per resource, not raised globally.

FHIR endpoint is configured via MEDBLOCKS_FHIR_BASE_URL in settings.
For the POC, this defaults to the Medblocks FHIR R4 API.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.models.check_in import CheckInExtraction, ExtractedSymptom
from app.services.hpo_validator import strip_invalid
from app.utils.config import get_settings

logger = logging.getLogger(__name__)

_SURVEY_CATEGORY = {
    "coding": [{
        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
        "code": "survey",
        "display": "Survey",
    }]
}

_HPO_SYSTEM = "https://hpo.jax.org/"


# ── Resource builders ─────────────────────────────────────────────────────────

def _build_symptom_observation(
    symptom: ExtractedSymptom,
    patient_id: str,
    check_in_time: datetime,
) -> dict[str, Any]:
    """
    Build a FHIR R4 Observation resource for a single extracted symptom.
    HPO IDs are validated before inclusion.
    """
    effective_time = (
        symptom.onset_time.isoformat()
        if symptom.onset_time
        else check_in_time.isoformat()
    )

    valid_hpo = strip_invalid(
        [t.model_dump() if hasattr(t, "model_dump") else t for t in symptom.hpo_terms]
    )

    # Primary code: first high-confidence HPO term, or plain text if none
    if valid_hpo:
        primary = valid_hpo[0]
        code = {
            "coding": [{
                "system": _HPO_SYSTEM,
                "code": primary["hpo_id"],
                "display": primary["label"],
            }],
            "text": symptom.symptom_text,
        }
    else:
        code = {"text": symptom.symptom_text}

    # Additional HPO codings as extra entries
    additional_codings = [
        {
            "system": _HPO_SYSTEM,
            "code": t["hpo_id"],
            "display": t["label"],
        }
        for t in valid_hpo[1:]
    ]
    if additional_codings and "coding" in code:
        code["coding"].extend(additional_codings)

    # Build components (all non-null fields)
    components: list[dict] = [
        {
            "code": {"text": "severity"},
            "valueInteger": symptom.severity,
        },
        {
            "code": {"text": "body_system"},
            "valueString": symptom.body_system,
        },
    ]

    if symptom.probable_trigger:
        components.append({
            "code": {"text": "probable_trigger"},
            "valueString": symptom.probable_trigger,
        })
    if symptom.trigger_delay_minutes is not None:
        components.append({
            "code": {"text": "trigger_delay_minutes"},
            "valueInteger": symptom.trigger_delay_minutes,
        })
    if symptom.duration_minutes is not None:
        components.append({
            "code": {"text": "duration_minutes"},
            "valueInteger": symptom.duration_minutes,
        })
    if symptom.sleep_quality is not None:
        components.append({
            "code": {"text": "sleep_quality"},
            "valueInteger": symptom.sleep_quality,
        })
    if symptom.activity_level:
        components.append({
            "code": {"text": "activity_level"},
            "valueString": symptom.activity_level,
        })
    if symptom.stress_level is not None:
        components.append({
            "code": {"text": "stress_level"},
            "valueInteger": symptom.stress_level,
        })
    if symptom.dietary_notes:
        components.append({
            "code": {"text": "dietary_notes"},
            "valueString": symptom.dietary_notes,
        })
    if symptom.cycle_phase:
        components.append({
            "code": {"text": "cycle_phase"},
            "valueString": symptom.cycle_phase,
        })
    if valid_hpo:
        components.append({
            "code": {"text": "hpo_confidence"},
            "valueString": valid_hpo[0].get("confidence", "medium"),
        })

    return {
        "resourceType": "Observation",
        "status": "final",
        "category": [_SURVEY_CATEGORY],
        "code": code,
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": effective_time,
        "component": components,
    }


def _build_no_symptom_observation(
    patient_id: str,
    check_in_time: datetime,
    sleep_quality: int | None = None,
    activity_level: str | None = None,
    stress_level: int | None = None,
) -> dict[str, Any]:
    """
    Build a FHIR R4 Observation for a no-symptom baseline day.
    These observations are valuable for pattern analysis.
    """
    components: list[dict] = [
        {"code": {"text": "is_no_symptom_day"}, "valueBoolean": True},
    ]
    if sleep_quality is not None:
        components.append({"code": {"text": "sleep_quality"}, "valueInteger": sleep_quality})
    if activity_level:
        components.append({"code": {"text": "activity_level"}, "valueString": activity_level})
    if stress_level is not None:
        components.append({"code": {"text": "stress_level"}, "valueInteger": stress_level})

    return {
        "resourceType": "Observation",
        "status": "final",
        "category": [_SURVEY_CATEGORY],
        "code": {"text": "No symptoms reported — baseline day"},
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": check_in_time.isoformat(),
        "component": components,
    }


# ── Pure mapping function ─────────────────────────────────────────────────────

def extraction_to_observations(
    extraction: CheckInExtraction,
    patient_id: str,
    check_in_time: datetime | None = None,
) -> list[dict[str, Any]]:
    """
    Convert a validated CheckInExtraction to a list of FHIR Observation dicts.
    Pure function — no I/O.
    """
    now = check_in_time or datetime.now(timezone.utc)

    if extraction.is_no_symptom_day:
        # Collect any context fields from the first symptom entry (if present)
        # On a no-symptom day, symptoms list should be empty per validation,
        # but context fields may have been captured in the extraction dict directly.
        return [
            _build_no_symptom_observation(
                patient_id=patient_id,
                check_in_time=now,
            )
        ]

    observations = []
    for symptom in extraction.symptoms:
        obs = _build_symptom_observation(
            symptom=symptom,
            patient_id=patient_id,
            check_in_time=now,
        )
        observations.append(obs)

    return observations


# ── FHIR write function ───────────────────────────────────────────────────────

async def write_check_in(
    observations: list[dict[str, Any]],
    patient_id: str,
    access_token: str | None = None,
) -> list[str]:
    """
    POST each Observation to the FHIR endpoint.
    Returns a list of resource IDs for successfully written observations.
    Partial success: failed writes are logged but do not raise.
    """
    settings = get_settings()
    base_url = getattr(settings, "medblocks_fhir_base_url", None) or "https://fhir.medblocks.com/fhir/R4"
    endpoint = f"{base_url.rstrip('/')}/Observation"

    fhir_token = access_token or settings.medblocks_fhir_bearer_token
    headers: dict[str, str] = {"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"}
    if fhir_token:
        headers["Authorization"] = f"Bearer {fhir_token}"

    # TODO: REMOVE BEFORE COMMIT — debug logging for FHIR write diagnostics
    import json as _json
    import time as _time

    token_preview = f"{fhir_token[:8]}\u2026{fhir_token[-4:]}" if fhir_token and len(fhir_token) > 12 else (repr(fhir_token))
    logger.warning(
        "DEBUG write_check_in: endpoint=%s observations=%d token=%s auth_header=%s",
        endpoint,
        len(observations),
        token_preview,
        "Bearer ***" if fhir_token else "NONE — unauthenticated",
    )

    resource_ids: list[str] = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        for idx, obs in enumerate(observations):
            obs_summary = {
                "resourceType": obs.get("resourceType"),
                "subject": obs.get("subject"),
                "code_text": obs.get("code", {}).get("text"),
                "component_count": len(obs.get("component", [])),
                "effectiveDateTime": obs.get("effectiveDateTime"),
            }
            logger.warning(
                "DEBUG FHIR obs[%d/%d] summary: %s",
                idx + 1,
                len(observations),
                obs_summary,
            )
            logger.debug("DEBUG FHIR obs[%d] full payload: %s", idx + 1, _json.dumps(obs))

            t0 = _time.monotonic()
            try:
                response = await client.post(endpoint, json=obs, headers=headers)
                elapsed_ms = int((_time.monotonic() - t0) * 1000)
                logger.warning(
                    "DEBUG FHIR obs[%d] response: status=%s elapsed_ms=%d headers=%s",
                    idx + 1,
                    response.status_code,
                    elapsed_ms,
                    dict(response.headers),
                )
                response.raise_for_status()

                # FHIR servers put the new resource ID in the Location header:
                # Location: <base>/Observation/<id>/_history/1
                # The response body may be empty (without Prefer: return=representation).
                resource_id = ""

                location = response.headers.get("Location") or response.headers.get("location", "")
                if location:
                    # Extract the ID segment: .../Observation/<id>/_history/...
                    parts = [p for p in location.rstrip("/").split("/") if p]
                    try:
                        history_idx = parts.index("_history")
                        resource_id = parts[history_idx - 1]
                    except (ValueError, IndexError):
                        resource_id = parts[-1] if parts else ""
                    logger.warning(
                        "DEBUG FHIR obs[%d] Location header=%s → id=%s",
                        idx + 1, location, resource_id,
                    )

                # Fall back to response body if Location yielded nothing
                if not resource_id:
                    raw_body = response.text
                    logger.warning(
                        "DEBUG FHIR obs[%d] no Location id — raw body (%d chars): %s",
                        idx + 1, len(raw_body), raw_body[:500],
                    )
                    try:
                        created = response.json()
                        resource_id = created.get("id", "")
                    except Exception:
                        pass

                if resource_id:
                    resource_ids.append(resource_id)
                    logger.warning("FHIR Observation written: %s for patient %s", resource_id, patient_id)
                else:
                    logger.warning(
                        "FHIR write succeeded (status=%s) but no ID found in Location header "
                        "or response body for patient %s",
                        response.status_code,
                        patient_id,
                    )
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "FHIR write HTTP error %s for patient %s — url=%s body=%s",
                    exc.response.status_code,
                    patient_id,
                    exc.response.url,
                    exc.response.text[:500],
                )
            except httpx.TimeoutException as exc:
                logger.error(
                    "FHIR write timed out after 15s for patient %s (obs %d/%d): %s",
                    patient_id,
                    idx + 1,
                    len(observations),
                    exc,
                )
            except httpx.ConnectError as exc:
                logger.error(
                    "FHIR write connection error for patient %s — endpoint=%s: %s",
                    patient_id,
                    endpoint,
                    exc,
                )
            except Exception as exc:
                logger.error(
                    "FHIR write unexpected error for patient %s (obs %d/%d): %s: %s",
                    patient_id,
                    idx + 1,
                    len(observations),
                    type(exc).__name__,
                    exc,
                )

    return resource_ids
