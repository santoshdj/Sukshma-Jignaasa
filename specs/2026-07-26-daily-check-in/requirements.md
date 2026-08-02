# Requirements — Daily Check-In AI Mode

**Spec directory:** `specs/2026-07-26-daily-check-in/`
**Phase:** Phase 1 — The Diagnostic Companion
**Branch:** `phase-1-daily-check-in`

---

## Scope

### What This Feature Does

The daily check-in is the primary data collection surface of the companion app. It is a two-part hybrid flow:

1. **Quick-log widget** — a patient taps to log known/saved symptoms (severity slider, duration picker). This fires first and takes under 30 seconds.
2. **AI follow-up conversation** — after the quick-log (or directly if the patient skips it), the AI opens a contextual conversation to capture triggers, context, and any new or unlisted symptoms. The AI decides when it has sufficient signal, presents a structured confirmation summary, and the patient confirms before anything is saved.

The central AI capability is **free-text to structured phenotype record extraction**: the AI parses the patient's natural language and maps observations to structured records using HPO (Human Phenotype Ontology) terms alongside severity, context, and trigger fields.

### Included in This Spec

| Capability | Description |
|---|---|
| Quick-log widget | Severity (1–10 slider) + duration picker for pre-saved symptoms |
| AI check-in conversation | Adaptive-tone conversational AI that extracts structured fields from free text |
| HPO phenotype mapping | AI maps symptom free-text to HPO term codes (HP:XXXXXXX) |
| Structured field extraction | Severity, duration, onset time, body system, triggers, context fields |
| Confirmation summary | AI presents extracted record before saving; patient confirms or corrects |
| FHIR Observation write | Confirmed records written to Medblocks FHIR R4 as `Observation` resources |
| No-symptom baseline logging | When patient reports feeling fine, a `no-symptoms` Observation is still logged |
| Good-day gentle follow-up | One AI follow-up ("Any energy or sleep worth noting?") before closing a no-symptom session |

### Excluded from This Spec

- Pattern Narrator analysis (separate AI mode — Phase 1, separate spec)
- Appointment Prep (separate AI mode — Phase 1, separate spec)
- Hypothesis Surfacer (Phase 2)
- Wearable/sensor data ingestion
- Push notification scheduling (Phase 2)
- Clinician-facing views

---

## Data Model

### Extracted Fields per Check-In Entry

| Field | Type | Required | Source | Notes |
|-------|------|----------|--------|-------|
| `symptom_text` | string | Yes | Patient free-text | Raw, preserved verbatim |
| `hpo_terms` | `HPOTerm[]` | Yes | AI extraction | Array; may be empty if no mappable HPO term found |
| `body_system` | enum | Yes | AI extraction | See body system enum below |
| `severity` | int 1–10 | Yes | Quick-log or AI extraction | |
| `duration_minutes` | int | No | AI extraction | Null if not mentioned |
| `onset_time` | ISO datetime | No | AI extraction | Defaults to check-in timestamp if not specified |
| `probable_trigger` | string | No | AI extraction | Free-text; may be null |
| `trigger_delay_minutes` | int | No | AI extraction | Time between trigger and symptom onset |
| `sleep_quality` | int 1–10 | No | AI extraction | |
| `activity_level` | enum | No | AI extraction | `low \| moderate \| high` |
| `stress_level` | int 1–10 | No | AI extraction | |
| `dietary_notes` | string | No | AI extraction | Free-text |
| `cycle_phase` | enum \| null | No | AI extraction | `follicular \| ovulatory \| luteal \| menstrual \| not_applicable \| unknown` |
| `is_no_symptom_day` | bool | Yes | AI decision | True when patient reports no symptoms |

### HPOTerm Type

```typescript
interface HPOTerm {
  hpo_id: string;        // e.g. "HP:0012378"
  label: string;         // e.g. "Fatigue"
  confidence: "high" | "medium" | "low";  // AI's mapping confidence
}
```

### Body System Enum

`neurological | musculoskeletal | cardiovascular | autonomic | gastrointestinal | immunological | dermatological | endocrine | respiratory | other`

### FHIR Observation Shape (Medblocks)

Each extracted symptom entry is stored as a separate FHIR `Observation` resource:

```json
{
  "resourceType": "Observation",
  "status": "final",
  "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "survey"}]}],
  "code": {
    "coding": [{
      "system": "https://hpo.jax.org/",
      "code": "HP:0012378",
      "display": "Fatigue"
    }],
    "text": "<patient's original free-text>"
  },
  "subject": {"reference": "Patient/<medblocks_patient_id>"},
  "effectiveDateTime": "<onset_time ISO>",
  "component": [
    {"code": {"text": "severity"}, "valueInteger": 7},
    {"code": {"text": "body_system"}, "valueString": "neurological"},
    {"code": {"text": "probable_trigger"}, "valueString": "prolonged standing"},
    {"code": {"text": "sleep_quality"}, "valueInteger": 5},
    {"code": {"text": "activity_level"}, "valueString": "moderate"},
    {"code": {"text": "stress_level"}, "valueInteger": 6},
    {"code": {"text": "cycle_phase"}, "valueString": "luteal"},
    {"code": {"text": "hpo_confidence"}, "valueString": "high"}
  ]
}
```

No-symptom days are logged as a single Observation with `code.text = "No symptoms reported"`, `status = "final"`, and a component `is_no_symptom_day: true`.

---

## Decisions

### D1 — Conversation Flow: Hybrid Start, AI-Decided End

**Start:** Quick-log widget fires first (known symptoms, ≤30 seconds). Then the AI opens a follow-up conversation with context-aware opening. If the patient skips the quick-log, the AI opens directly.

**End:** The AI ends the conversation when it judges it has sufficient signal (minimum: at least one symptom or no-symptom declaration + any available context). It then presents a structured confirmation card:

```
Here's what I captured today:
• Fatigue (HP:0012378) — severity 7/10, triggered by standing, luteal phase
• Joint pain, knees (HP:0002829) — severity 5/10
• Sleep quality: 5/10 | Stress: 6/10

Does this look right? [Confirm & Save] [Edit]
```

Patient confirms → FHIR write. Patient edits → AI re-opens for correction.

**Maximum turn limit:** 8 exchanges (safety net; AI should resolve in 3–5 under normal conditions).

**Rationale:** AI-decided end prevents open-ended conversations that exhaust low-energy patients. The confirmation card gives the patient final control over what gets stored — consistent with the human review gate principle in the constitution.

### D2 — HPO Phenotype Mapping

The AI must attempt to map every symptom to at least one HPO term. HPO is the standard vocabulary for rare disease phenotyping used by NORD, Orphanet, and Matchmaker Exchange — it makes the stored data interoperable with rare disease registries.

If no confident HPO mapping exists, `hpo_terms` is an empty array and the raw `symptom_text` is preserved. The AI must not hallucinate HPO codes — any code it outputs must exist in the HPO ontology.

**Implementation approach:** The AI prompt includes a curated subset of the most clinically relevant HPO terms for the EDS/POTS/MCAS/autoimmune cluster (~200 terms). The AI selects from this list. Unknown symptoms are flagged for later review. Full HPO ontology lookup (via HPO API) is a Phase 2 enhancement.

### D3 — Adaptive Tone

The AI's conversational register adapts based on signals in the patient's messages:

| Signal | Tone mode | Behaviour |
|---|---|---|
| Short, terse responses | **Brief** | Fewer words, direct questions, faster to summary |
| Mentions pain/fatigue/crash | **Gentle** | Shorter messages, warm acknowledgement before next question |
| Detailed responses, asks questions | **Engaged** | More conversational, slight elaboration allowed |

All modes share the same guardrails and extraction logic. Tone affects length and phrasing only — not content or clinical framing.

The AI never comments on the severity of what the patient reports ("that sounds really serious" is prohibited). It acknowledges without amplifying.

### D4 — Good Days / No-Symptom Sessions

When a patient reports feeling fine:
1. AI acknowledges warmly (brief, not effusive)
2. AI asks exactly one gentle follow-up: *"Any energy levels or sleep worth noting for your records?"*
3. Whether or not the patient responds, a `no-symptoms` FHIR Observation is logged
4. Session ends — no further extraction attempts

Rationale: No-symptom days are statistically valuable baseline data for pattern analysis. The one follow-up captures context that improves pattern signal without pressuring the patient on a good day.

---

## Context

### Tone Rules

- Never use the word "diagnosis" in the check-in flow
- Never interpret what a symptom might mean clinically ("that could be...")
- Never use clinical jargon without a plain-language follow-up
- Acknowledge difficulty briefly and move on — do not dwell
- All AI messages in check-in mode: ≤40 words (brief mode), ≤60 words (engaged mode)
- Confirmation card is always shown before saving — no silent writes

### Stack Pointers

- **LLM:** Claude Haiku via LiteLLM (low latency for conversational extraction)
- **Orchestration:** LangGraph node `check_in_node` within `CompanionState` graph
- **FHIR write:** Medblocks Python SDK (`mb.patients.records()` / FHIR Observation POST)
- **Backend endpoint:** `POST /check-in/start`, `POST /check-in/message`, `POST /check-in/confirm`
- **Frontend:** Next.js chat interface component, quick-log widget component
- **State:** LangGraph `MemorySaver` per session thread

### Existing Patterns to Follow

- LangGraph node structure: mirrors `app/agents/clinical_auditor.py` in `healthcare-audit-agent`
- FHIR write pattern: mirrors `SukshmaDrishti/src/routes/connections.ts` (Medblocks SDK)
- Pydantic output schema: required for all LLM responses — no unvalidated free-text written to FHIR
- Markdown code-fence stripping on LLM output before JSON parse (known pattern from `healthcare-audit-agent`)
