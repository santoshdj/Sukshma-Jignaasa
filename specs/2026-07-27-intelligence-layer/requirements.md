# Requirements — Phase 2: The Intelligence Layer

**Spec directory:** `specs/2026-07-27-intelligence-layer/`
**Phase:** Phase 2 — The Intelligence Layer
**Branch:** `phase-2-intelligence-layer`

---

## Scope

### What This Phase Delivers

Three features that collectively enable the Hypothesis Surfacer — the central Phase 2 capability:

| # | Feature | What it does |
|---|---------|-------------|
| 1 | **Rare disease knowledge base** | Structured profiles of 50+ rare conditions embedded in ChromaDB; the retrieval layer for the Hypothesis Surfacer |
| 2 | **EHR connection (Medblocks OAuth)** | Patient connects their EHR; historical FHIR records (Condition, Observation, MedicationRequest, AllergyIntolerance, Encounter) are pulled into the analysis context |
| 3 | **Hypothesis Surfacer** | RAG-based Claude Sonnet node that compares the patient's HPO-coded symptom fingerprint + EHR records against the knowledge base and produces ranked, uncertainty-framed hypothesis profiles |

The shareable clinical report and push notifications are explicitly deferred to Phase 2b.

### Included in This Spec

- `app/data/rare_disease_profiles.json` — 50+ curated rare condition profiles
- `app/services/knowledge_base.py` — ChromaDB vector store (build + search)
- `app/services/ehr_reader.py` — Medblocks `records()` paginated FHIR pull
- `app/routers/ehr.py` — Patient Access connection endpoints (start → redirect → return)
- `app/agents/hypothesis_node.py` — RAG-based Claude Sonnet node
- `app/agents/hypothesis_graph.py` — LangGraph graph wiring + HITL review gate
- `app/routers/hypothesis.py` — REST endpoints for hypothesis flow
- `app/models/hypothesis.py` — Pydantic models for all hypothesis data shapes
- Frontend: EHR connection flow pages + Hypothesis results UI

### Excluded from This Spec

- Shareable clinical report (PDF export) — deferred
- Push notifications — deferred
- Wearable integration — Phase 2b
- Pattern Narrator (pattern over time) — separate Phase 1 feature; not blocking this phase
- The 60-day unlock gate enforced server-side (enforced by checking observation count, not calendar days)

---

## Data Models

### Rare Disease Profile

```python
class RareDiseaseProfile(BaseModel):
    condition_id: str              # e.g. "EDS-HYPERMOBILE"
    name: str                      # e.g. "Hypermobile Ehlers-Danlos Syndrome (hEDS)"
    omim_code: str | None          # e.g. "130020"
    orpha_code: str | None         # e.g. "ORPHA:285"
    description: str               # 2-3 sentence plain-language description
    cardinal_hpo_terms: list[str]  # HPO IDs that are highly diagnostic
    supportive_hpo_terms: list[str]  # HPO IDs that support but aren't diagnostic
    common_comorbidities: list[str]  # Other condition IDs commonly co-occurring
    trigger_patterns: list[str]    # Free-text trigger patterns (e.g. "orthostatic stress")
    key_biomarkers: list[str]      # Lab/test clues (e.g. "normal ANA", "elevated tryptase")
    demographics: str              # Who is typically affected
    specialist_type: str           # Who to see (e.g. "Connective tissue/genetics specialist")
```

### Hypothesis Profile (output of Hypothesis Surfacer)

```python
class HypothesisProfile(BaseModel):
    condition_id: str
    condition_name: str
    match_strength: Literal["high", "medium", "low"]
    matching_symptoms: list[str]   # Patient's HPO terms that align with this condition
    missing_signals: list[str]     # Key symptoms/tests not yet observed — discussion points
    plain_language_explanation: str  # ≤100 words, patient-facing, no clinical interpretation
    specialist_type: str
    confidence_note: str           # Mandatory uncertainty framing
    discuss_with_specialist: bool  # Always True — enforced in output schema

class HypothesisReport(BaseModel):
    patient_id: str
    generated_at: datetime
    observation_count: int         # How many check-ins were in scope
    ehr_records_included: bool     # Whether EHR data was incorporated
    hypotheses: list[HypothesisProfile]  # Ranked high → medium → low
    summary: str                   # ≤150 words overall narrative
    guardrail_disclosure: str      # Mandatory: "These are patterns, not diagnoses..."
    human_approved: bool           # False until patient reviews and confirms
```

### EHR Connection State

```python
class EHRConnection(BaseModel):
    patient_id: str
    medblocks_patient_id: str
    connection_status: Literal["not_connected", "pending", "active", "failed"]
    connected_at: datetime | None
    fhir_resource_counts: dict[str, int]  # e.g. {"Condition": 5, "Observation": 23}
    last_synced_at: datetime | None
```

### FHIR records pulled from EHR

| Resource type | What it adds to context |
|---|---|
| `Condition` | Existing diagnoses — narrows or expands hypothesis space |
| `Observation` | Lab results — key biomarkers for rare disease differentiation |
| `MedicationRequest` | Current medications — suggests prior diagnostic attempts |
| `AllergyIntolerance` | Relevant for MCAS and immune-mediated conditions |
| `Encounter` | Visit history — number of specialists seen, timeframe |

---

## Decisions

### D1 — RAG Architecture: ChromaDB (local)

**Decision:** ChromaDB persisted locally at `data/chroma_db/` for the POC. No external vector DB service required.

**Embedding model:** `text-embedding-3-small` (OpenAI) or Anthropic's `voyage-medical-2` if available. Falls back to a lightweight local sentence-transformers model (`all-MiniLM-L6-v2`) if no embedding API key is set, allowing zero-cost local development.

**What gets embedded:** Each disease profile is embedded as: `"{name}. {description}. Key HPO terms: {cardinal + supportive terms joined}. Triggers: {trigger_patterns}. Biomarkers: {key_biomarkers}"` — a single document per condition.

**Query:** Patient's symptom fingerprint is encoded as: `"{HPO labels joined}. Triggers observed: {trigger texts}. EHR conditions: {condition names from FHIR}"` — then top-5 profiles are retrieved.

**Rationale:** ChromaDB runs in-process with no infrastructure setup. For a POC targeting 50–200 conditions, in-memory + local persistence is sufficient. pgvector is the documented upgrade path.

### D2 — Medblocks Patient Access: Hosted Page Flow

**Decision:** Use Medblocks' hosted Patient Access page. The app provides `patient_id` and `return_url`; Medblocks handles source discovery and EHR authorization UI.

**Rationale:** The Medblocks skill explicitly recommends the hosted page when Medblocks should handle source discovery. Building a custom source selection UI is Phase 2b scope.

**Connection flow (per Medblocks skill):**

```
1. POST /ehr/connect/start
   → mb.patientSession.init({ patient_id, return_url })
   → return { auth_url }  ← frontend redirects patient here

2. Patient authorizes at Medblocks hosted page

3. Patient lands at /ehr/connected?patient_id=...&patient_session_id=...
   → parseReturnUrl(params) → { patient_id, patient_session_id }
   → mb.patientSession.retrieve(patient_session_id) ← server-side verify
   → mb.patients.getConnections(patient_id) ← check active connections

4. POST /ehr/sync (triggered by frontend after return)
   → mb.patients.records(patient_id) paginated pull
   → store in PostgreSQL as raw FHIR JSON
   → update EHRConnection status
```

**Records may not be immediately available** after connection (per Medblocks skill). The UI shows a "syncing" state; a manual retry is available. Production would use a webhook.

### D3 — Hypothesis Surfacer: Observation Count Gate

**Decision:** The Hypothesis Surfacer requires a minimum of **30 FHIR Observations** from the patient's check-in history (not 60 calendar days as originally specified in ROADMAP.md). 30 observations is a more reliable signal gate — a patient logging daily hits this in a month, but a less frequent logger gets there when they have meaningful data regardless of calendar time.

**Rationale:** Calendar days are a poor proxy for data density. 30 observations with symptom+trigger fields populated provides sufficient signal for pattern retrieval.

### D4 — Hypothesis AI Node: No Diagnosis Language

All hypothesis output must pass the same guardrail patterns as the check-in node. Additional Phase 2 guardrails:

- Never use `"you have"`, `"you likely have"`, `"this is consistent with a diagnosis of"`
- Every hypothesis framed as `"your symptom pattern shares features with"`
- Every profile includes `"discuss_with_specialist": true` — enforced in Pydantic schema (hardcoded, not LLM-set)
- `confidence_note` field is mandatory — the LLM must populate it with explicit uncertainty language
- Overall guardrail disclosure appended to every `HypothesisReport` (not written by LLM)

### D5 — EHR Records Storage

**Decision:** Raw FHIR resources pulled from Medblocks are stored in PostgreSQL as `jsonb` columns, not re-written to the Medblocks FHIR store. The Medblocks FHIR store holds the patient's *own* logged check-ins; EHR-sourced records are kept separately in `ehr_records` table.

**Rationale:** Keeps the two data streams clearly separated. Check-in observations (written by the app) remain in Medblocks. EHR records (pulled from connected EHRs) remain in PostgreSQL with their original resource IDs.

---

## Context

### Tone Rules (Hypothesis Surfacer)

- All output is framed as "pattern sharing features with" — never as possibility of diagnosis
- Match strength labels: "Strong pattern overlap" / "Moderate pattern overlap" / "Some shared features" — not "high/medium/low probability"  
- The `guardrail_disclosure` field appended to every report (not LLM-generated): *"These profiles highlight symptom pattern similarities only. They are not a medical diagnosis and cannot replace a clinical evaluation. Please discuss any of these patterns with a specialist who can assess your full history."*
- Plain language explanation: ≤100 words, no jargon, no clinical interpretation

### Stack Pointers

- **Vector DB:** `chromadb` Python package (local persistence)
- **Embeddings:** `openai` (text-embedding-3-small) via LiteLLM; local fallback via `sentence-transformers`
- **LLM:** Claude Sonnet via LiteLLM (`get_analysis_llm()` — already built in `app/services/llm_service.py`)
- **Medblocks SDK:** Already installed in `medblocks==0.0.2`; use Python SDK via `httpx` calls (not Node SDK) since backend is Python. The Node SDK from `SukshmaDrishti` is the reference for the flow.
- **EHR router:** New `app/routers/ehr.py` — follows `app/routers/check_in.py` pattern
- **Database:** New `ehr_connections` and `ehr_records` tables via Alembic migration
- **No PHI in logs:** Raw FHIR resources must never be logged at INFO level

### Existing Patterns to Follow

- LangGraph node pattern: `app/agents/check_in_node.py` + `app/agents/check_in_graph.py`
- Pydantic output schema with `field_validator` and `model_validator`: `app/models/check_in.py`
- FHIR writer pattern (httpx async): `app/services/fhir_writer.py`
- Markdown code-fence stripping on LLM output: established in all existing agent nodes
