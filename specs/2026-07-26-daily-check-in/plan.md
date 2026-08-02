# Implementation Plan — Daily Check-In AI Mode

Each task group is independently implementable. Complete and test each group before starting the next.

---

## Group 1 — HPO Vocabulary + AI Extraction Schema

**Goal:** Define the data contracts and HPO term subset before writing any LLM code.

1.1 Create `app/data/hpo_terms.json` — curated subset of ~200 HPO terms most relevant to EDS/POTS/MCAS/autoimmune overlap cluster. Include: `hpo_id`, `label`, `aliases`, `body_system`.

1.2 Create Pydantic models in `app/models/check_in.py`:
  - `HPOTerm` — `hpo_id: str`, `label: str`, `confidence: Literal["high","medium","low"]`
  - `ExtractedSymptom` — all fields from the data model in requirements.md
  - `CheckInExtraction` — `symptoms: list[ExtractedSymptom]`, `is_no_symptom_day: bool`, `session_notes: str`
  - `CheckInMessage` — role/content for conversation history
  - `CheckInState` — full LangGraph state TypedDict

1.3 Write unit tests for Pydantic model validation in `tests/test_check_in_models.py`.

---

## Group 2 — LangGraph Check-In Node

**Goal:** Implement the AI extraction node with HPO mapping, adaptive tone, and structured output.

2.1 Create `app/agents/check_in_node.py`:
  - System prompt with: HPO term list, extraction schema, tone rules, guardrail list, confirmation summary format
  - `extract_from_message(state: CheckInState) -> dict` — calls Claude Haiku via LiteLLM, parses `CheckInExtraction` from response
  - Adaptive tone selection logic based on message length and keyword signals
  - Markdown code-fence stripping before JSON parse
  - Turn counter enforcement (max 8 exchanges)

2.2 Create `app/agents/check_in_graph.py`:
  - `StateGraph(CheckInState)` with nodes: `extract`, `should_continue`, `confirm`
  - `should_continue` edge: checks turn count + whether AI has sufficient signal → routes to `confirm` or `extract`
  - `interrupt_before=["confirm"]` — graph pauses for patient confirmation before FHIR write
  - `MemorySaver` checkpointer per `session_id`

2.3 Write `tests/test_check_in_node.py`:
  - Mock Claude Haiku responses for 5 synthetic patient scenarios (see validation.md)
  - Assert all guardrail prohibitions (no "diagnosis", no clinical interpretation)
  - Assert HPO codes are from the curated vocabulary only (no hallucinated codes)
  - Assert `is_no_symptom_day` is correctly detected

---

## Group 3 — FHIR Write Path

**Goal:** Map confirmed `CheckInExtraction` to FHIR `Observation` resources and write to Medblocks.

3.1 Create `app/services/fhir_writer.py`:
  - `extraction_to_observations(extraction: CheckInExtraction, patient_id: str) -> list[dict]` — converts each `ExtractedSymptom` to a FHIR Observation JSON dict per the shape in requirements.md
  - `write_check_in(observations: list[dict], patient_id: str) -> list[str]` — POSTs each Observation to Medblocks, returns resource IDs
  - No-symptom baseline Observation construction
  - Error handling: if any single Observation write fails, log and continue (partial success is acceptable)

3.2 Create `app/services/hpo_validator.py`:
  - `validate_hpo_id(hpo_id: str) -> bool` — checks ID against `hpo_terms.json` vocabulary
  - Strips any AI-hallucinated HPO IDs before FHIR write

3.3 Write `tests/test_fhir_writer.py`:
  - Mock Medblocks API calls
  - Assert correct FHIR Observation structure for symptom entries
  - Assert correct no-symptom Observation structure
  - Assert HPO validation strips invalid codes

---

## Group 4 — Backend API Endpoints

**Goal:** FastAPI endpoints that drive the frontend check-in flow.

4.1 Create `app/routers/check_in.py`:

  ```
  POST /check-in/start
    Body: { patient_id: str, quick_log_entries?: QuickLogEntry[] }
    Returns: { session_id: str, ai_message: str, status: "in_progress" }

  POST /check-in/message
    Body: { session_id: str, patient_message: str }
    Returns: { ai_message: str, status: "in_progress" | "awaiting_confirmation" }
    When status="awaiting_confirmation": includes { confirmation_summary: ConfirmationSummary }

  POST /check-in/confirm
    Body: { session_id: str, decision: "confirm" | "edit", edit_notes?: str }
    Returns: { status: "saved" | "editing", fhir_observation_ids?: list[str] }
  ```

4.2 Create `app/models/api_models.py`:
  - `QuickLogEntry` — `symptom_name: str`, `severity: int`, `duration_minutes: int | None`
  - `ConfirmationSummary` — structured summary card fields
  - All request/response Pydantic models for the three endpoints

4.3 Wire router into `main.py`.

4.4 Write `tests/test_check_in_api.py`:
  - FastAPI `TestClient` integration tests
  - Full session flow: start → message → awaiting_confirmation → confirm → saved
  - Assert 400 on invalid session_id
  - Assert confirmation step is never skipped (no direct FHIR write without patient confirm)

---

## Group 5 — Frontend Check-In UI

**Goal:** Next.js components for the quick-log widget and AI chat interface.

5.1 Create `src/components/QuickLogWidget.tsx`:
  - Grid of saved symptom buttons (pull from user's symptom profile)
  - Severity slider (1–10) per selected symptom
  - Duration picker (minutes/hours)
  - "Start check-in" CTA → calls `POST /check-in/start` with quick log entries

5.2 Create `src/components/CheckInChat.tsx`:
  - Chat bubble interface (patient right, AI left)
  - Streaming or polling for AI responses
  - Input field with send button
  - Auto-scroll to latest message
  - Max-width constraint for readability on mobile

5.3 Create `src/components/ConfirmationCard.tsx`:
  - Structured summary display (symptom list, severity, triggers, context)
  - HPO term badges with confidence indicators
  - [Confirm & Save] / [Edit] buttons
  - Calls `POST /check-in/confirm`

5.4 Create `src/app/check-in/page.tsx`:
  - Orchestrates QuickLogWidget → CheckInChat → ConfirmationCard flow
  - Session state management via Zustand
  - Offline queue: if network unavailable, store locally and sync when reconnected

---

## Group 6 — Integration + End-to-End

**Goal:** Full check-in flow working against Medblocks sandbox.

6.1 Configure `.env` with Medblocks sandbox API key and test patient ID.

6.2 Manual end-to-end: complete a check-in session with a real Claude Haiku call → verify FHIR Observations appear in Medblocks.

6.3 Write `tests/test_e2e_check_in.py` (mocked LLM, real FHIR structure assertions):
  - Run full API flow from `POST /check-in/start` to confirmed `saved`
  - Assert FHIR Observation IDs returned
  - Assert no-symptom session produces exactly one baseline Observation

6.4 Add GitHub Actions workflow (`.github/workflows/ci.yml`):
  - `uv run pytest tests/` on every PR
  - `bunx tsc --noEmit` for frontend type-check
