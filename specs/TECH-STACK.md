# Tech Stack — Sukshma-Jignaasa

All technology choices are justified against the product's requirements: patient-facing mobile-first PWA, longitudinal symptom intelligence, LLM-powered multi-mode AI companion, FHIR R4 clinical data storage, and privacy-first architecture.

---

## Architecture Overview

```
Patient (Browser / PWA)
        │
        ▼
  Next.js 14+ Frontend (TypeScript)
  - Symptom quick-log UI
  - AI chat check-in interface
  - Pattern timeline visualisation
  - Appointment prep review + sharing
        │  HTTPS REST / Server Actions
        ▼
  FastAPI Backend (Python 3.12)
  - Auth (Medblocks patient sessions)
  - Symptom log CRUD
  - LangGraph AI orchestration layer
  - FHIR resource construction
  - Appointment prep document generation
        │
        ├──────────────────────────────────────────┐
        ▼                                          ▼
  Medblocks FHIR R4                         PostgreSQL
  (Clinical data)                           (App state)
  - Observation (symptoms)                  - User preferences
  - Condition (known/suspected)             - AI conversation history
  - CarePlan (post-diagnosis)               - Appointment records
  - Patient + connections                   - Notification settings
        │
        ▼
  LiteLLM Router
  ├── Claude Haiku  ← daily check-in extraction (low latency)
  └── Claude Sonnet ← Pattern Narrator, Hypothesis Surfacer, Appointment Prep
```

---

## Frontend

| Concern | Technology | Rationale |
|---------|-----------|-----------|
| Framework | **Next.js 14+** (App Router) | Server components for data-heavy views; client components for chat UI; SSR for fast initial load on mobile |
| Language | **TypeScript** | Type safety across API contracts and FHIR resource shapes |
| Styling | **Tailwind CSS v4** | Utility-first, mobile-first, matches existing workspace patterns |
| Components | **shadcn/ui** | Accessible, composable components; consistent with `applykit` |
| PWA | **next-pwa** | Service worker for offline logging; home screen install prompt; background sync for queued logs |
| Charts | **Recharts** | Symptom timeline visualisation, co-occurrence heatmaps, severity trends |
| State | **Zustand** | Lightweight client state for chat session, quick-log queue, offline buffer |
| Forms | **React Hook Form + Zod** | Validated symptom log forms; schema shared with backend |

---

## Backend

| Concern | Technology | Rationale |
|---------|-----------|-----------|
| Framework | **FastAPI** (Python 3.12) | Async, typed, matches all existing AI service patterns in workspace |
| AI orchestration | **LangGraph** | Multi-mode state machine (Pattern Narrator / Hypothesis Surfacer / Appointment Prep nodes); human-in-the-loop review gate; matches `healthcare-audit-agent` architecture |
| LLM routing | **LiteLLM** | Provider-agnostic; Anthropic default; swap to OpenAI/Gemini via config |
| LLM (check-in) | **Claude Haiku** | Fast, cheap, sufficient for conversational extraction of structured fields from free-text |
| LLM (analysis) | **Claude Sonnet** | Strong medical knowledge, long context (90-day symptom histories), structured JSON output |
| ORM | **SQLAlchemy 2.0 + Alembic** | PostgreSQL app state; migration-managed schema |
| Validation | **Pydantic v2** | Request/response models; FHIR resource construction validation |
| Auth | **Medblocks patient sessions** | OAuth via Medblocks `patientSession.init()` → FHIR-scoped access token |
| Background jobs | **APScheduler** (Phase 1) → **Celery + Redis** (Phase 2) | Nightly pattern analysis runs, push notification triggers |
| Testing | **pytest + pytest-asyncio** | Unit tests for AI nodes; integration tests for FHIR write paths |

---

## Data Storage

### Medblocks FHIR R4 (Clinical Data)

All clinical observations are stored as FHIR R4 resources via the Medblocks API. No custom clinical schema — FHIR resources are the canonical data model.

| FHIR Resource | Mapped to | Example |
|--------------|-----------|---------|
| `Observation` | Symptom log entry | Fatigue severity 7/10, onset 2026-07-24T14:30 |
| `Observation` | Trigger log entry | Activity trigger: 20-min walk preceding fatigue |
| `Condition` | Suspected/known condition | Suspected hEDS (clinical status: unconfirmed) |
| `CarePlan` | Post-diagnosis care plan | Phase 2 |
| `Patient` | Patient identity | UUID-linked, no PII required in app |

Patient FHIR resources are pseudonymised — the Medblocks `patient_id` UUID is the only identifier stored server-side. Display name and email are stored only in the PostgreSQL `users` table, never in FHIR resources.

### PostgreSQL (App State)

| Table | Content |
|-------|---------|
| `users` | UUID, display name, email, Medblocks patient_id (FK), created_at |
| `symptom_profiles` | User's tracked symptom list, body system mapping, display preferences |
| `ai_conversations` | Conversation history per session (check-in dialogue, pattern review sessions) |
| `appointments` | Upcoming appointments, linked prep summaries, share status |
| `notifications` | Push notification preferences, scheduled reminder state |

---

## AI Orchestration (LangGraph)

Three AI modes are implemented as a `StateGraph` with mode-specific nodes. Each mode is independently specced, prompted, and testable.

```
CompanionState
  ├── patient_id
  ├── mode: "check_in" | "pattern_narration" | "hypothesis" | "appointment_prep"
  ├── symptom_history: list[FHIRObservation]      # loaded from Medblocks
  ├── conversation_history: list[Message]
  ├── ai_output: dict                             # mode-specific structured output
  ├── human_approved: bool                        # review gate (appointment_prep)
  └── errors: list[str]

Graph:
  load_context → route_by_mode
    ├── check_in_node         (Claude Haiku)  → extract structured fields → save to FHIR
    ├── pattern_narrator_node (Claude Sonnet) → temporal analysis → PatternReport
    ├── hypothesis_node       (Claude Sonnet) → symptom fingerprint match → HypothesisList
    └── appointment_prep_node (Claude Sonnet) → structured summary → [INTERRUPT for review] → share
```

All nodes that produce patient-facing clinical content implement the three safety guardrails:
1. **Hard refusal list** enforced in system prompt (no diagnosis, no medication advice, no lab interpretation, emergency redirect)
2. **Uncertainty framing** required in output schema (every hypothesis carries `confidence: "low|medium|high"` + mandatory `discuss_with_specialist: true`)
3. **Human review gate** — `appointment_prep_node` uses `interrupt_before=["share_gate"]`; patient confirms before any summary is shared

---

## Infrastructure

| Component | Technology | Notes |
|-----------|-----------|-------|
| Containerisation | **Docker + Docker Compose** | Local dev: frontend + backend + PostgreSQL in one `compose up` |
| Deployment | **Railway / Render** (Phase 1) | Simple PaaS; no infrastructure overhead for MVP |
| Database | **PostgreSQL 16** (managed) | Railway Postgres or Render Postgres |
| FHIR | **Medblocks** (hosted) | No self-hosted FHIR infrastructure required |
| File storage | **Cloudflare R2** | Generated PDF appointment prep documents |
| Secrets | **Environment variables** | `.env` locally; platform secrets manager in production |
| CI | **GitHub Actions** | Lint + type-check + pytest on every PR |

---

## Package Managers

| Layer | Manager |
|-------|---------|
| Python (backend) | **uv** |
| JavaScript (frontend) | **Bun** |

---

## Security Posture

- All API endpoints require authenticated Medblocks session token
- PHI (symptom observations) stored only in Medblocks FHIR — never logged, never in error messages
- PostgreSQL tables contain only pseudonymised references (UUID, no clinical content)
- LLM prompts never include patient name, DOB, or direct identifiers — only UUID + clinical observations
- HTTPS enforced everywhere; no HTTP fallback
- AI output always includes disclosure: "Generated by Sukshma-Jignaasa AI companion. Not a medical diagnosis. Discuss with your healthcare provider."

---

## Spec-Driven Development Conventions

Following AI Spec-Driven Development principles:

1. **Every AI mode has a spec before a prompt** — input contract, output contract, guardrail list, evaluation dataset
2. **Output schemas are typed** — all LLM responses parsed against Pydantic models; free-text responses rejected
3. **Guardrails are testable** — unit tests assert that prohibited phrases never appear in any AI output
4. **FHIR resources are the source of truth** — application state is derived from FHIR; PostgreSQL holds only presentation/UX metadata
5. **Human review gate is non-negotiable** — appointment prep summaries cannot be shared without explicit patient confirmation
