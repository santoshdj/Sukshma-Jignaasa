"""
Hypothesis and EHR Pydantic models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from typing_extensions import TypedDict

# ── Rare Disease Profile (matches rare_disease_profiles.json) ─────────────────

class RareDiseaseProfile(BaseModel):
    condition_id: str
    name: str
    omim_code: str | None = None
    orpha_code: str | None = None
    description: str
    cardinal_hpo_terms: list[str]
    supportive_hpo_terms: list[str]
    common_comorbidities: list[str] = Field(default_factory=list)
    trigger_patterns: list[str] = Field(default_factory=list)
    key_biomarkers: list[str] = Field(default_factory=list)
    demographics: str
    specialist_type: str


# ── Hypothesis output models ───────────────────────────────────────────────────

MatchStrength = Literal["high", "medium", "low"]


class HypothesisProfile(BaseModel):
    """
    One condition hypothesis produced by the Hypothesis Surfacer.
    discuss_with_specialist is hardcoded True — the LLM cannot set it to False.
    """
    condition_id: str = Field(..., min_length=1)
    condition_name: str = Field(..., min_length=1)
    match_strength: MatchStrength
    matching_symptoms: list[str] = Field(default_factory=list)
    missing_signals: list[str] = Field(default_factory=list)
    plain_language_explanation: str = Field(
        ...,
        max_length=500,
        description="≤100 words, no jargon, no clinical interpretation",
    )
    specialist_type: str
    confidence_note: str = Field(
        ...,
        min_length=10,
        description="Mandatory uncertainty framing — AI must populate this",
    )
    discuss_with_specialist: bool = True

    @field_validator("plain_language_explanation", mode="before")
    @classmethod
    def truncate_explanation(cls, v: object) -> str:
        """Silently truncate LLM output that exceeds the character limit."""
        s = str(v) if not isinstance(v, str) else v
        if len(s) > 500:
            return s[:497] + "..."
        return s

    @model_validator(mode="after")
    def enforce_discuss_with_specialist(self) -> "HypothesisProfile":
        """This field is ALWAYS True. LLM output cannot override it."""
        self.discuss_with_specialist = True
        return self


_GUARDRAIL_DISCLOSURE = (
    "These profiles highlight symptom pattern similarities only. "
    "They are not a medical diagnosis and cannot replace a clinical evaluation. "
    "Please discuss any of these patterns with a specialist who can assess your full history."
)


class HypothesisReport(BaseModel):
    """
    Full output of the Hypothesis Surfacer — approved by patient before sharing.
    guardrail_disclosure is backend-appended, never LLM-generated.
    """
    patient_id: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    observation_count: int = Field(..., ge=0)
    ehr_records_included: bool = False
    hypotheses: list[HypothesisProfile] = Field(default_factory=list)
    summary: str = Field(
        ...,
        max_length=1000,
        description="≤150 words overall narrative",
    )

    @field_validator("summary", mode="before")
    @classmethod
    def truncate_summary(cls, v: object) -> str:
        """Silently truncate LLM output that exceeds the character limit."""
        s = str(v) if not isinstance(v, str) else v
        if len(s) > 1000:
            return s[:997] + "..."
        return s
    guardrail_disclosure: str = Field(
        default=_GUARDRAIL_DISCLOSURE,
        description="Always appended by backend — never written by LLM",
    )
    human_approved: bool = False

    @model_validator(mode="after")
    def enforce_guardrail_disclosure(self) -> "HypothesisReport":
        """Guardrail disclosure is always the canonical text, never LLM-generated."""
        self.guardrail_disclosure = _GUARDRAIL_DISCLOSURE
        return self

    @field_validator("hypotheses")
    @classmethod
    def enforce_discuss_with_specialist_in_all(
        cls, profiles: list[HypothesisProfile]
    ) -> list[HypothesisProfile]:
        for p in profiles:
            p.discuss_with_specialist = True
        return profiles


# ── EHR connection models ──────────────────────────────────────────────────────

EHRConnectionStatus = Literal["not_connected", "pending", "active", "failed"]


class EHRConnection(BaseModel):
    patient_id: str
    connection_status: EHRConnectionStatus = "not_connected"
    connected_at: datetime | None = None
    fhir_resource_counts: dict[str, int] = Field(default_factory=dict)
    last_synced_at: datetime | None = None


class EHRRecord(BaseModel):
    patient_id: str
    resource_type: str
    resource_id: str
    resource_json: dict


# ── LangGraph state ────────────────────────────────────────────────────────────

class HypothesisState(TypedDict):
    session_id: str
    patient_id: str

    # Inputs assembled before the node runs
    symptom_fingerprint: dict      # { hpo_ids, trigger_texts, severity_pattern }
    ehr_context: dict              # { conditions, key_observations, medications }
    observation_count: int

    # Retrieved profiles from ChromaDB
    retrieved_profiles: list[dict]

    # AI output
    hypothesis_report: dict | None  # HypothesisReport dict

    # HITL
    human_approved: bool

    # Pipeline metadata
    status: str    # "running" | "awaiting_review" | "approved" | "failed"
    errors: list[str]


# ── API request / response models ─────────────────────────────────────────────

class StartHypothesisRequest(BaseModel):
    patient_id: str = Field(..., min_length=1)


class StartHypothesisResponse(BaseModel):
    session_id: str
    patient_id: str
    status: str
    observations_available: int
    check_ins_available: int
    min_check_ins_required: int = 30


class ApproveHypothesisRequest(BaseModel):
    decision: Literal["approve", "regenerate"]
    feedback: str = Field(default="", description="Required when decision='regenerate'")


class HypothesisStatusResponse(BaseModel):
    session_id: str
    patient_id: str
    status: str


class StartEHRConnectionRequest(BaseModel):
    patient_id: str = Field(..., min_length=1)
    return_url: str = Field(..., min_length=1)


class StartEHRConnectionResponse(BaseModel):
    auth_url: str


class CompleteEHRConnectionRequest(BaseModel):
    patient_id: str = Field(..., min_length=1)
    patient_session_id: str = Field(..., min_length=1)


class SyncEHRRequest(BaseModel):
    patient_id: str = Field(..., min_length=1)


class SyncEHRResponse(BaseModel):
    synced_counts: dict[str, int]
    patient_id: str
