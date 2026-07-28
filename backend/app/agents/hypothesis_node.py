"""
Hypothesis Surfacer Node
------------------------
Claude Sonnet (via get_analysis_llm) compares the patient's symptom fingerprint
against top-K rare disease profiles retrieved from ChromaDB.

Input:
  - HPO-coded symptom history from Medblocks FHIR (last 90 days)
  - EHR context from local DB (Condition, Observation, MedicationRequest)
  - Top-K disease profiles retrieved from ChromaDB

Output:
  HypothesisReport — ranked hypotheses with mandatory guardrail framing.
  discuss_with_specialist is ALWAYS True (enforced by schema).
  guardrail_disclosure is ALWAYS the canonical text (enforced by schema).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from langchain_core.messages import HumanMessage, SystemMessage

from app.models.hypothesis import (
    HypothesisReport,
    HypothesisState,
    RareDiseaseProfile,
)
from app.services.knowledge_base import search_by_fingerprint
from app.services.llm_service import get_analysis_llm
from app.utils.config import get_settings

logger = logging.getLogger(__name__)

_MEDBLOCKS_BASE = "https://app.medblocks.com"
_GUARDRAIL_PATTERNS = [
    re.compile(r"\byou (have|likely have|probably have)\b", re.IGNORECASE),
    re.compile(r"\bdiagnos(is|e|ed|ing)\b", re.IGNORECASE),
    re.compile(r"\bthis is consistent with\b", re.IGNORECASE),
    re.compile(r"\bthis (could|may|might) be\b", re.IGNORECASE),
    re.compile(r"\bI (believe|think|suspect)\b", re.IGNORECASE),
]

MIN_OBSERVATIONS = 30

# ── Guardrail check ───────────────────────────────────────────────────────────

def check_hypothesis_guardrails(text: str) -> list[str]:
    return [p.pattern for p in _GUARDRAIL_PATTERNS if p.search(text)]


# ── Data assembly helpers ─────────────────────────────────────────────────────

async def _get_patient_observations(patient_id: str) -> list[dict]:
    """Fetch last 90 days of FHIR Observations from Medblocks (async for use in tests)."""
    return _get_patient_observations_sync(patient_id)


def _get_patient_observations_sync(patient_id: str) -> list[dict]:
    """Fetch last 90 days of FHIR Observations from Medblocks (sync, used by LangGraph node)."""
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    headers = {
        "Authorization": f"Bearer {settings.medblocks_api_key}",
        "Accept": "application/json",
    }
    observations: list[dict] = []
    params: dict = {"count": 200, "resource_type": "Observation"}

    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.get(
                f"{_MEDBLOCKS_BASE}/patients/{patient_id}/records",
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("data", []):
                resource = item.get("resource") or item
                effective = resource.get("effectiveDateTime", "")
                if effective:
                    try:
                        obs_time = datetime.fromisoformat(effective.replace("Z", "+00:00"))
                        if obs_time >= cutoff:
                            observations.append(resource)
                    except ValueError:
                        observations.append(resource)
                else:
                    observations.append(resource)
    except Exception as exc:
        logger.warning("Could not fetch observations for %s: %s", patient_id, exc)

    return observations


def _build_symptom_fingerprint(observations: list[dict]) -> dict:
    """Extract HPO IDs, triggers, and severity patterns from FHIR Observations."""
    hpo_ids: set[str] = set()
    trigger_texts: list[str] = []
    severity_map: dict[str, list[int]] = {}

    for obs in observations:
        # Extract HPO codes
        for coding in obs.get("code", {}).get("coding", []):
            if coding.get("system") == "https://hpo.jax.org/" and coding.get("code"):
                hpo_ids.add(coding["code"])

        # Extract components
        for comp in obs.get("component", []):
            comp_code = comp.get("code", {}).get("text", "")
            if comp_code == "probable_trigger" and comp.get("valueString"):
                trigger_texts.append(comp["valueString"])
            elif comp_code == "severity" and comp.get("valueInteger"):
                symptom_text = obs.get("code", {}).get("text", "unknown")
                severity_map.setdefault(symptom_text, []).append(comp["valueInteger"])

    avg_severities = {k: sum(v) / len(v) for k, v in severity_map.items()}

    return {
        "hpo_ids": list(hpo_ids),
        "trigger_texts": list(set(trigger_texts))[:10],
        "severity_pattern": avg_severities,
        "observation_count": len(observations),
    }


def _build_ehr_context(patient_id: str) -> dict:
    """Pull EHR-sourced records from the local DB for context."""
    from app.db.session import get_session
    from app.db.models import EHRRecordRow

    conditions: list[str] = []
    key_observations: list[str] = []
    medications: list[str] = []

    with get_session() as session:
        records = session.query(EHRRecordRow).filter_by(patient_id=patient_id).all()
        for r in records:
            rj = r.resource_json or {}
            if r.resource_type == "Condition":
                name = rj.get("code", {}).get("text") or rj.get("code", {}).get("coding", [{}])[0].get("display", "")
                if name:
                    conditions.append(name)
            elif r.resource_type == "Observation":
                # Only include abnormal or notable observations
                interp = rj.get("interpretation", [{}])
                code_text = rj.get("code", {}).get("text", "")
                if interp and code_text:
                    key_observations.append(f"{code_text}")
            elif r.resource_type == "MedicationRequest":
                med = rj.get("medicationCodeableConcept", {}).get("text", "") or \
                      rj.get("medicationCodeableConcept", {}).get("coding", [{}])[0].get("display", "")
                if med:
                    medications.append(med)

    return {
        "conditions": conditions[:20],
        "key_observations": key_observations[:15],
        "medications": medications[:15],
        "ehr_records_included": len(conditions) > 0 or len(key_observations) > 0,
    }


# ── Prompt ────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a medical pattern analysis assistant helping a patient understand which rare disease symptom patterns are most similar to their own experiences.

## Critical constraints — you MUST follow these:
- NEVER say "you have", "you likely have", "you probably have", or any variant
- NEVER use the word "diagnosis" or "diagnose"
- NEVER say "this is consistent with" or "this could be" as a diagnostic statement
- Frame ALL findings as: "your symptom pattern shares features with"
- Every hypothesis MUST include explicit uncertainty in the confidence_note field
- discuss_with_specialist MUST be true for every hypothesis

## Output format
Return a single valid JSON object (no markdown fences):

{
  "hypotheses": [
    {
      "condition_id": "<from retrieved profiles>",
      "condition_name": "<full condition name>",
      "match_strength": "high|medium|low",
      "matching_symptoms": ["<symptom that appears in both the patient data and this condition>"],
      "missing_signals": ["<symptom or test that would strengthen or weaken this pattern>"],
      "plain_language_explanation": "<≤100 words. No jargon. Explain the pattern overlap in plain language.>",
      "specialist_type": "<who to see>",
      "confidence_note": "<mandatory uncertainty: e.g. 'Pattern similarity is suggestive, not diagnostic. Many symptoms overlap across conditions.'>",
      "discuss_with_specialist": true
    }
  ],
  "summary": "<≤150 words. Neutral narrative of the overall pattern. No conclusions about diagnosis.>"
}

Sort hypotheses: high match first, then medium, then low. Include only conditions from the retrieved profiles provided."""


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


# ── Main node ─────────────────────────────────────────────────────────────────

def hypothesis_node(state: HypothesisState) -> dict:
    """
    Run the hypothesis surfacer for one patient.
    Reads FHIR observations, fetches EHR context, searches ChromaDB,
    calls Claude Sonnet, validates output.
    """
    patient_id = state["patient_id"]
    logger.info("Hypothesis node running for %s", patient_id)

    # Get symptom fingerprint
    if not state.get("symptom_fingerprint"):
        observations = _get_patient_observations_sync(patient_id)
        fingerprint = _build_symptom_fingerprint(observations)
    else:
        fingerprint = state["symptom_fingerprint"]
        observations = []

    obs_count = fingerprint.get("observation_count", 0)

    # Enforce minimum observation gate
    if obs_count < MIN_OBSERVATIONS:
        return {
            "observation_count": obs_count,
            "status": "failed",
            "errors": state.get("errors", []) + [
                f"Insufficient data: {obs_count} observations (minimum {MIN_OBSERVATIONS} required)"
            ],
        }

    # Get EHR context
    ehr_context = state.get("ehr_context") or _build_ehr_context(patient_id)

    # Retrieve top profiles from ChromaDB
    retrieved = search_by_fingerprint(
        hpo_ids=fingerprint.get("hpo_ids", []),
        trigger_texts=fingerprint.get("trigger_texts", []),
        ehr_conditions=ehr_context.get("conditions", []),
        top_k=5,
    )

    if not retrieved:
        return {
            "status": "failed",
            "errors": state.get("errors", []) + ["Knowledge base returned no profiles"],
        }

    # Build prompt context
    profiles_text = json.dumps(
        [p.model_dump() for p in retrieved], indent=2
    )
    fingerprint_text = (
        f"HPO terms observed: {', '.join(fingerprint.get('hpo_ids', []))}\n"
        f"Triggers: {', '.join(fingerprint.get('trigger_texts', []))}\n"
        f"Severity patterns: {json.dumps(fingerprint.get('severity_pattern', {}))}\n"
        f"Observation count: {obs_count}\n"
    )
    ehr_text = (
        f"Known conditions (from EHR): {', '.join(ehr_context.get('conditions', ['None']))}\n"
        f"Notable observations: {', '.join(ehr_context.get('key_observations', ['None']))}\n"
        f"Medications: {', '.join(ehr_context.get('medications', ['None']))}\n"
    )

    # Regeneration context if applicable
    regen_note = ""
    if state.get("status") == "regenerate" and state.get("errors"):
        regen_note = f"\n\nPrevious report was regenerated. Patient feedback: {state['errors'][-1]}"

    user_prompt = (
        f"## Patient Symptom Fingerprint\n{fingerprint_text}\n"
        f"## EHR Context\n{ehr_text}\n"
        f"## Retrieved Disease Profiles (analyse only these)\n{profiles_text}"
        f"{regen_note}"
    )

    llm = get_analysis_llm()
    try:
        response = llm.invoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ])
        raw = _strip_fences(response.content)
        parsed = json.loads(raw)
    except Exception as exc:
        logger.error("Hypothesis node LLM failed: %s", exc)
        return {
            "status": "failed",
            "errors": state.get("errors", []) + [f"LLM error: {exc}"],
        }

    # Guardrail check on all text fields
    all_text = json.dumps(parsed)
    violations = check_hypothesis_guardrails(all_text)
    if violations:
        logger.warning("Hypothesis guardrail violations: %s", violations)
        # Clean the text but don't fail — schema enforcement handles it
        for pattern in _GUARDRAIL_PATTERNS:
            all_text = pattern.sub("[information withheld]", all_text)
        try:
            parsed = json.loads(all_text)
        except Exception:
            pass

    # Build and validate report (schema enforces guardrails)
    try:
        report = HypothesisReport(
            patient_id=patient_id,
            generated_at=datetime.now(timezone.utc),
            observation_count=obs_count,
            ehr_records_included=ehr_context.get("ehr_records_included", False),
            hypotheses=parsed.get("hypotheses", []),
            summary=parsed.get("summary", "Pattern analysis complete."),
        )
    except Exception as exc:
        logger.error("HypothesisReport validation failed: %s", exc)
        return {
            "status": "failed",
            "errors": state.get("errors", []) + [f"Report validation error: {exc}"],
        }

    logger.info(
        "Hypothesis node complete: %d hypotheses for %s",
        len(report.hypotheses), patient_id,
    )
    return {
        "symptom_fingerprint": fingerprint,
        "ehr_context": ehr_context,
        "retrieved_profiles": [p.model_dump() for p in retrieved],
        "hypothesis_report": report.model_dump(mode="json"),
        "observation_count": obs_count,
        "status": "awaiting_review",
    }
