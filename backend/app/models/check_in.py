"""
Check-in data models.

All models used by the daily check-in AI mode:
  - API request/response shapes
  - AI extraction output schema (validated before FHIR write)
  - LangGraph state TypedDict
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from typing_extensions import TypedDict

# ---------------------------------------------------------------------------
# HPO vocabulary — loaded once at module import
# ---------------------------------------------------------------------------

_HPO_VOCAB_PATH = Path(__file__).resolve().parents[2] / "app" / "data" / "hpo_terms.json"

def _load_hpo_vocab() -> set[str]:
    with _HPO_VOCAB_PATH.open("r", encoding="utf-8") as f:
        terms = json.load(f)
    return {t["hpo_id"] for t in terms}


VALID_HPO_IDS: set[str] = _load_hpo_vocab()

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

BodySystem = Literal[
    "neurological",
    "musculoskeletal",
    "cardiovascular",
    "autonomic",
    "gastrointestinal",
    "immunological",
    "dermatological",
    "endocrine",
    "respiratory",
    "other",
]

ActivityLevel = Literal["low", "moderate", "high"]

CyclePhase = Literal[
    "follicular",
    "ovulatory",
    "luteal",
    "menstrual",
    "not_applicable",
    "unknown",
]

HPOConfidence = Literal["high", "medium", "low"]

ToneMode = Literal["brief", "gentle", "engaged"]

CheckInStatus = Literal["in_progress", "awaiting_confirmation", "saved", "editing", "abandoned"]

# ---------------------------------------------------------------------------
# Core extraction types
# ---------------------------------------------------------------------------


class HPOTerm(BaseModel):
    """A mapped Human Phenotype Ontology term extracted from patient free-text."""

    hpo_id: str = Field(..., pattern=r"^HP:\d{7}$", description="HPO identifier e.g. HP:0012378")
    label: str = Field(..., min_length=1, description="Human-readable HPO label")
    confidence: HPOConfidence = Field(..., description="AI mapping confidence")

    @field_validator("hpo_id")
    @classmethod
    def hpo_id_must_be_in_vocabulary(cls, v: str) -> str:
        if v not in VALID_HPO_IDS:
            raise ValueError(
                f"HPO ID '{v}' is not in the curated vocabulary. "
                "Only vocabulary IDs may be written to FHIR."
            )
        return v


class ExtractedSymptom(BaseModel):
    """One symptom occurrence extracted from the patient's check-in text."""

    symptom_text: str = Field(..., min_length=1, description="Verbatim patient text preserved exactly")
    hpo_terms: list[HPOTerm] = Field(default_factory=list, description="Mapped HPO terms; empty if no confident match")
    body_system: BodySystem = Field(..., description="Primary body system")
    severity: int = Field(..., ge=1, le=10, description="Severity on a 1–10 scale")
    duration_minutes: int | None = Field(None, ge=0, description="Duration in minutes; null if not mentioned")
    onset_time: datetime | None = Field(None, description="Symptom onset; defaults to check-in time if null")

    @field_validator("severity", mode="before")
    @classmethod
    def coerce_severity(cls, v: object) -> int:
        """Default to 5 when LLM returns null for severity."""
        if v is None:
            return 5
        return int(v)

    @field_validator("onset_time", mode="before")
    @classmethod
    def coerce_onset_time(cls, v: object) -> datetime | None:
        """Return None for vague strings (e.g. 'evening') the LLM emits instead of ISO datetimes."""
        if v is None or isinstance(v, datetime):
            return v
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v)
            except (ValueError, TypeError):
                return None
        return None

    # Trigger fields
    probable_trigger: str | None = Field(None, description="Probable trigger in plain text; null if not identified")
    trigger_delay_minutes: int | None = Field(None, ge=0, description="Minutes between trigger and symptom onset")

    # Context fields
    sleep_quality: int | None = Field(None, ge=1, le=10)
    activity_level: ActivityLevel | None = None
    stress_level: int | None = Field(None, ge=1, le=10)
    dietary_notes: str | None = None
    cycle_phase: CyclePhase | None = None


class CheckInExtraction(BaseModel):
    """
    Complete structured output from the AI check-in extraction.
    Validated by Pydantic before any FHIR write occurs.
    """

    symptoms: list[ExtractedSymptom] = Field(default_factory=list)
    is_no_symptom_day: bool = Field(
        ...,
        description="True when the patient explicitly reports feeling fine / no symptoms",
    )
    session_notes: str = Field(
        default="",
        description="AI's brief internal note on the session (not shown to patient; not written to FHIR)",
    )
    tone_used: ToneMode = Field(
        default="engaged",
        description="Tone mode the AI used for this session",
    )

    @model_validator(mode="after")
    def no_symptoms_when_no_symptom_day(self) -> "CheckInExtraction":
        if self.is_no_symptom_day and self.symptoms:
            raise ValueError(
                "is_no_symptom_day is True but symptoms list is non-empty. "
                "Clear symptoms or set is_no_symptom_day=False."
            )
        return self


# ---------------------------------------------------------------------------
# Conversation / session types
# ---------------------------------------------------------------------------


class CheckInMessage(BaseModel):
    """A single message in the check-in conversation."""

    role: Literal["user", "assistant"] = Field(..., description="Message sender")
    content: str = Field(..., min_length=1, description="Message content")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class QuickLogEntry(BaseModel):
    """A pre-structured symptom entry from the quick-log widget."""

    symptom_name: str = Field(..., min_length=1)
    severity: int = Field(..., ge=1, le=10)
    duration_minutes: int | None = Field(None, ge=0)


class ConfirmationSummary(BaseModel):
    """
    Structured summary card shown to the patient before saving.
    The patient confirms or edits before any FHIR write.
    """

    symptoms: list[dict] = Field(
        ...,
        description="Human-readable symptom summaries for display",
    )
    context: dict = Field(
        default_factory=dict,
        description="Sleep, stress, activity context if captured",
    )
    is_no_symptom_day: bool
    message: str = Field(
        ...,
        description="AI's plain-language summary sentence shown to the patient",
    )


# ---------------------------------------------------------------------------
# LangGraph state
# ---------------------------------------------------------------------------


class CheckInState(TypedDict):
    """Shared state threaded through the check-in LangGraph StateGraph."""

    # Session identity
    session_id: str
    patient_id: str

    # Input
    quick_log_entries: list[dict]  # QuickLogEntry dicts

    # Conversation history
    conversation_history: list[dict]  # CheckInMessage dicts
    turn_count: int

    # AI extraction (populated incrementally)
    current_extraction: dict  # CheckInExtraction dict; None until first extraction
    tone_mode: str  # "brief" | "gentle" | "engaged"

    # Confirmation gate
    confirmation_summary: dict | None  # ConfirmationSummary dict; None until ready
    human_confirmed: bool

    # FHIR write results
    fhir_observation_ids: list[str]

    # Pipeline status
    status: str  # CheckInStatus
    errors: list[str]


# ---------------------------------------------------------------------------
# API request / response models
# ---------------------------------------------------------------------------


class StartCheckInRequest(BaseModel):
    patient_id: str = Field(..., min_length=1)
    quick_log_entries: list[QuickLogEntry] = Field(default_factory=list)


class StartCheckInResponse(BaseModel):
    session_id: str
    ai_message: str
    status: CheckInStatus


class CheckInMessageRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    patient_message: str = Field(..., min_length=1)


class CheckInMessageResponse(BaseModel):
    ai_message: str
    status: CheckInStatus
    confirmation_summary: ConfirmationSummary | None = None


class ConfirmCheckInRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    decision: Literal["confirm", "edit"] = Field(...)
    edit_notes: str | None = Field(None, description="Correction notes if decision='edit'")


class ConfirmCheckInResponse(BaseModel):
    status: CheckInStatus
    fhir_observation_ids: list[str] = Field(default_factory=list)
