"""
Appointment Prep Node
---------------------
Claude Sonnet (via get_analysis_llm) reads the patient's logged FHIR observations
and produces a structured pre-visit summary for specialist handoff.

Input:
  - Up to 90 days of FHIR Observations from Medblocks check-in writes
  - Aggregated symptom statistics (frequency, severity, triggers)

Output:
  AppointmentPrepSummary — top symptoms, trigger patterns, suggested
  patient questions, and a plain-language narrative.
  ai_disclosure is ALWAYS the canonical text (enforced by schema).
  human_approved starts False; set True only via /confirm endpoint.

Guardrails:
  - No diagnosis language
  - Questions framed as patient asks doctor, not clinical conclusions
  - Uncertainty embedded in all pattern descriptions
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import httpx
from langchain_core.messages import HumanMessage, SystemMessage

from app.models.appointment_prep import (
    AppointmentPrepState,
    AppointmentPrepSummary,
)
from app.services.llm_service import get_analysis_llm
from app.utils.config import get_settings

logger = logging.getLogger(__name__)

_MEDBLOCKS_BASE = "https://app.medblocks.com"

MIN_OBSERVATIONS = 1  # any logged data is worth summarising for a specialist visit

_GUARDRAIL_PATTERNS = [
    re.compile(r"\byou (have|likely have|probably have)\b", re.IGNORECASE),
    re.compile(r"\bdiagnos(is|e|es|ed|ing)\b", re.IGNORECASE),
    re.compile(r"\bthis (is|could be|may be) consistent with\b", re.IGNORECASE),
    re.compile(r"\bI (believe|think|suspect)\b", re.IGNORECASE),
    re.compile(r"\bthis (could|may|might) indicate\b", re.IGNORECASE),
    re.compile(r"\brecommend(s|ed|ing)?\b", re.IGNORECASE),
]


def check_prep_guardrails(text: str) -> list[str]:
    return [p.pattern for p in _GUARDRAIL_PATTERNS if p.search(text)]


# ── FHIR fetch ────────────────────────────────────────────────────────────────

def _fetch_observations(patient_id: str, days: int = 90) -> list[dict]:
    """
    Fetch FHIR Observations for the patient from the Medblocks FHIR server.
    Uses the same fallback strategy as hypothesis_node (server-side filter
    then client-side filter if the server doesn't index subject).
    """
    settings = get_settings()
    fhir_base = settings.medblocks_fhir_base_url.rstrip("/")
    cutoff_str = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
    target_ref = f"Patient/{patient_id}"

    headers = {
        "Authorization": f"Bearer {settings.medblocks_fhir_bearer_token}",
        "Accept": "application/fhir+json",
    }

    def _resources_from_bundle(bundle: dict) -> list[dict]:
        results: list[dict] = []
        for entry in bundle.get("entry", []):
            resource = entry.get("resource") or entry
            if resource.get("resourceType") == "Observation":
                results.append(resource)
        return results

    def _within_cutoff(obs: dict) -> bool:
        effective = obs.get("effectiveDateTime", "")
        if not effective:
            return True
        try:
            dt = datetime.fromisoformat(effective.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt >= cutoff_dt
        except (ValueError, TypeError):
            return True

    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            resp = client.get(
                f"{fhir_base}/Observation",
                headers=headers,
                params={"subject": target_ref, "date": f"ge{cutoff_str}", "_count": "200"},
            )
            resp.raise_for_status()
            bundle = resp.json()
            observations = _resources_from_bundle(bundle)

            if observations:
                logger.info(
                    "Appointment prep: fetched %d observations for %s",
                    len(observations), patient_id,
                )
                return observations

            # Fallback: server doesn't index subject — fetch all, filter client-side
            logger.warning(
                "Appointment prep: subject filter returned 0 for %s — falling back to client-side filter",
                patient_id,
            )
            all_obs: list[dict] = []
            next_url: str | None = f"{fhir_base}/Observation"
            next_params: dict | None = {"_count": "50", "date": f"ge{cutoff_str}"}
            page = 0

            while next_url and page < 20:
                page += 1
                fetch_resp = client.get(
                    next_url,
                    headers=headers,
                    params=next_params if page == 1 else None,
                    timeout=20.0,
                )
                fetch_resp.raise_for_status()
                page_bundle = fetch_resp.json()
                page_obs = _resources_from_bundle(page_bundle)

                for obs in page_obs:
                    subject_ref = obs.get("subject", {}).get("reference", "")
                    if subject_ref == target_ref and _within_cutoff(obs):
                        all_obs.append(obs)

                links = {lnk["relation"]: lnk["url"] for lnk in page_bundle.get("link", [])}
                next_url = links.get("next")
                next_params = None

                if len(all_obs) >= 200:
                    break

            logger.info(
                "Appointment prep: client-side filter: %d observations for %s after %d page(s)",
                len(all_obs), patient_id, page,
            )
            return all_obs

    except Exception as exc:
        logger.warning("Appointment prep: could not fetch observations for %s: %s", patient_id, exc)
        return []


# ── Aggregation ───────────────────────────────────────────────────────────────

def _aggregate_observations(observations: list[dict]) -> dict:
    """
    Aggregate raw FHIR Observations into structured statistics for the LLM prompt.
    Returns a dict with symptom_stats, trigger_index, dates, and count.
    """
    # symptom_stats: hpo_id|name → {name, hpo_id, body_system, severities, dates, triggers}
    symptom_stats: dict[str, dict] = defaultdict(lambda: {
        "name": "",
        "hpo_id": None,
        "body_system": "other",
        "severities": [],
        "dates": [],
        "triggers": [],
    })

    dates: list[str] = []

    for obs in observations:
        code_text = obs.get("code", {}).get("text", "")
        codings = obs.get("code", {}).get("coding", [])
        hpo_id = None
        for coding in codings:
            if coding.get("system") == "https://hpo.jax.org/" and coding.get("code"):
                hpo_id = coding["code"]
                break

        key = hpo_id or code_text or "unknown"
        stat = symptom_stats[key]
        stat["name"] = stat["name"] or code_text or (codings[0].get("display", "") if codings else "")
        stat["hpo_id"] = stat["hpo_id"] or hpo_id

        effective = obs.get("effectiveDateTime", "")
        if effective:
            dates.append(effective[:10])  # YYYY-MM-DD
            stat["dates"].append(effective[:10])

        for comp in obs.get("component", []):
            comp_code = comp.get("code", {}).get("text", "")
            if comp_code == "severity" and comp.get("valueInteger") is not None:
                stat["severities"].append(comp["valueInteger"])
            elif comp_code == "body_system" and comp.get("valueString"):
                stat["body_system"] = comp["valueString"]
            elif comp_code == "probable_trigger" and comp.get("valueString"):
                stat["triggers"].append(comp["valueString"])

        # Infer body system from HPO display if not in components
        if not stat["body_system"] or stat["body_system"] == "other":
            display = (codings[0].get("display", "") if codings else "").lower()
            if any(w in display for w in ("fatigue", "orthostatic", "tachycardia", "dizz")):
                stat["body_system"] = "autonomic"
            elif any(w in display for w in ("pain", "joint", "muscle", "tender")):
                stat["body_system"] = "musculoskeletal"
            elif any(w in display for w in ("headache", "migraine", "cognitive", "brain fog")):
                stat["body_system"] = "neurological"
            elif any(w in display for w in ("nausea", "bloat", "stomach", "bowel")):
                stat["body_system"] = "gastrointestinal"

    # Build final symptom summaries
    symptom_summaries = []
    for stat in symptom_stats.values():
        name = stat["name"] or "Unknown symptom"
        freq = max(len(stat["dates"]), 1)
        severities = stat["severities"] or [5]
        avg_sev = round(sum(severities) / len(severities), 1)
        last_date = max(stat["dates"]) if stat["dates"] else (dates[0] if dates else "")
        triggers = list(dict.fromkeys(stat["triggers"]))[:3]  # dedupe, top 3
        symptom_summaries.append({
            "name": name,
            "hpo_id": stat["hpo_id"],
            "body_system": stat["body_system"],
            "frequency": freq,
            "avg_severity": avg_sev,
            "last_observed": last_date,
            "common_triggers": triggers,
        })

    symptom_summaries.sort(key=lambda s: s["frequency"] * s["avg_severity"], reverse=True)

    return {
        "symptom_summaries": symptom_summaries[:10],  # top 10 to the LLM
        "date_range_start": min(dates) if dates else "",
        "date_range_end": max(dates) if dates else "",
        "observation_count": len(observations),
    }


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a medical record assistant helping a patient organise their symptom history before a specialist appointment.

## Your role
You summarise ONLY what the patient has logged. You do NOT interpret what symptoms mean clinically.

## Guardrails — you MUST NEVER:
- Say "you have", "you likely have", "this could be", or anything diagnostic
- Use the word "diagnosis" or "diagnose"
- Recommend tests, medications, or treatments
- Say "this is consistent with" as a diagnostic statement
- Express medical conclusions — stick to description of patterns observed in the data
- Suggest an emergency action or express alarm

## Suggested questions rules
- Frame every question as: "Could my [symptom] be related to...?" or "I've noticed [pattern] — is that worth investigating?"
- Questions are tools for the patient to start a conversation, NOT clinical assessments
- Generate 3–5 specific, useful questions grounded in the actual symptom data provided

## Output format
Return a single valid JSON object (no markdown fences, no extra text):
{
  "top_symptoms": [
    {
      "name": "<symptom name>",
      "hpo_id": "<HP:XXXXXXX or null>",
      "body_system": "<body system>",
      "frequency": <int>,
      "avg_severity": <float 1-10>,
      "last_observed": "<YYYY-MM-DD>"
    }
  ],
  "trigger_patterns": [
    {
      "symptom": "<symptom name>",
      "trigger": "<trigger description>",
      "description": "<≤60 words, plain language, no clinical interpretation>",
      "frequency_label": "frequently|sometimes|occasionally"
    }
  ],
  "suggested_questions": [
    {
      "question": "<patient question for specialist, ≤200 chars>",
      "context": "<brief note on why this question is relevant, ≤200 chars>"
    }
  ],
  "narrative": "<≤250 words, plain-language overview of the symptom picture. No clinical interpretation. Describe what was logged, when, and any patterns visible in the data.>"
}

Include up to 5 top_symptoms, up to 4 trigger_patterns (only if triggers were actually logged), and 3–5 suggested_questions.
If no triggers were logged, return an empty trigger_patterns list.
"""


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


# ── Main node ─────────────────────────────────────────────────────────────────

def appointment_prep_node(state: AppointmentPrepState) -> dict:
    """
    Generate the appointment prep summary for a patient.
    Fetches FHIR observations, aggregates statistics, calls Claude Sonnet,
    validates output, and returns partial state updates.
    """
    patient_id = state["patient_id"]
    logger.info("Appointment prep node running for %s", patient_id)

    # ── Fetch observations ────────────────────────────────────────────────────
    observations = _fetch_observations(patient_id, days=90)
    obs_count = len(observations)

    if obs_count < MIN_OBSERVATIONS:
        return {
            "observation_count": obs_count,
            "status": "failed",
            "errors": state.get("errors", []) + [
                f"No observations found for patient {patient_id}"
            ],
        }

    # ── Aggregate ─────────────────────────────────────────────────────────────
    aggregated = _aggregate_observations(observations)

    if not aggregated["symptom_summaries"]:
        return {
            "observation_count": obs_count,
            "status": "failed",
            "errors": state.get("errors", []) + ["Could not extract symptom data from observations"],
        }

    # ── Build LLM prompt ──────────────────────────────────────────────────────
    regen_note = ""
    if state.get("status") == "regenerate" and state.get("errors"):
        regen_note = f"\n\nThis is a regeneration. Patient feedback: {state['errors'][-1]}"

    user_prompt = (
        f"## Patient Symptom Log Summary\n"
        f"Logging period: {aggregated['date_range_start']} to {aggregated['date_range_end']}\n"
        f"Total observations: {obs_count}\n\n"
        f"## Symptom Statistics\n"
        f"{json.dumps(aggregated['symptom_summaries'], indent=2)}"
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
        logger.error("Appointment prep node LLM failed for %s: %s", patient_id, exc)
        return {
            "observation_count": obs_count,
            "status": "failed",
            "errors": state.get("errors", []) + [f"LLM error: {exc}"],
        }

    # ── Guardrail check ───────────────────────────────────────────────────────
    all_text = json.dumps(parsed)
    violations = check_prep_guardrails(all_text)
    if violations:
        logger.warning("Appointment prep guardrail violations for %s: %s", patient_id, violations)
        for pattern in _GUARDRAIL_PATTERNS:
            all_text = pattern.sub("[withheld]", all_text)
        try:
            parsed = json.loads(all_text)
        except Exception:
            pass  # schema validators will catch residual issues

    # ── Build and validate summary ────────────────────────────────────────────
    try:
        summary = AppointmentPrepSummary(
            patient_id=patient_id,
            generated_at=datetime.now(timezone.utc),
            observation_count=obs_count,
            date_range_start=aggregated["date_range_start"],
            date_range_end=aggregated["date_range_end"],
            top_symptoms=parsed.get("top_symptoms", []),
            trigger_patterns=parsed.get("trigger_patterns", []),
            suggested_questions=parsed.get("suggested_questions", []),
            narrative=parsed.get("narrative", "Summary not available."),
        )
    except Exception as exc:
        logger.error("AppointmentPrepSummary validation failed for %s: %s", patient_id, exc)
        return {
            "observation_count": obs_count,
            "status": "failed",
            "errors": state.get("errors", []) + [f"Summary validation error: {exc}"],
        }

    logger.info(
        "Appointment prep complete: %d symptoms, %d questions for %s",
        len(summary.top_symptoms), len(summary.suggested_questions), patient_id,
    )

    return {
        "observation_count": obs_count,
        "prep_summary": summary.model_dump(mode="json"),
        "status": "awaiting_review",
    }
