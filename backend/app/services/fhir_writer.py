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

    headers: dict[str, str] = {"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    resource_ids: list[str] = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        for obs in observations:
            try:
                response = await client.post(endpoint, json=obs, headers=headers)
                response.raise_for_status()
                created = response.json()
                resource_id = created.get("id", "")
                if resource_id:
                    resource_ids.append(resource_id)
                    logger.info("FHIR Observation written: %s for patient %s", resource_id, patient_id)
                else:
                    logger.warning("FHIR write succeeded but no ID returned for patient %s", patient_id)
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "FHIR write HTTP error %s for patient %s: %s",
                    exc.response.status_code,
                    patient_id,
                    exc.response.text[:200],
                )
            except Exception as exc:
                logger.error("FHIR write failed for patient %s: %s", patient_id, exc)

    return resource_ids
