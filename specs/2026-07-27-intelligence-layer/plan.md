# Implementation Plan — Phase 2: The Intelligence Layer

Each group is independently implementable. Complete and verify each group before starting the next.

---

## Group 1 — Rare Disease Knowledge Base

**Goal:** Build and populate the ChromaDB vector store with 50+ curated disease profiles.

1.1 Add dependencies to `backend/pyproject.toml`:
   - `chromadb>=0.5.0`
   - `sentence-transformers>=3.0.0` (local embedding fallback)

1.2 Create `backend/app/data/rare_disease_profiles.json`:
   - 50+ conditions in the EDS/POTS/MCAS/autoimmune overlap cluster
   - Each entry: `condition_id`, `name`, `omim_code`, `orpha_code`, `description`, `cardinal_hpo_terms`, `supportive_hpo_terms`, `common_comorbidities`, `trigger_patterns`, `key_biomarkers`, `demographics`, `specialist_type`
   - Priority conditions: hEDS, POTS, MCAS, MECFS, fibromyalgia, lupus (SLE), Sjögren's, mixed connective tissue disease, antiphospholipid syndrome, small fiber neuropathy, autoimmune autonomic ganglionopathy, hereditary alpha tryptasemia, UCTD, PANS/PANDAS, stiff person syndrome, myositis variants, Raynaud's + systemic sclerosis, Marfan syndrome, Loeys-Dietz syndrome, vascular EDS, primary immunodeficiency variants

1.3 Create `backend/app/models/hypothesis.py`:
   - `RareDiseaseProfile` Pydantic model
   - `HypothesisProfile` Pydantic model (with hardcoded `discuss_with_specialist=True` enforced by `model_validator`)
   - `HypothesisReport` Pydantic model (with mandatory `guardrail_disclosure` field)
   - `EHRConnection` Pydantic model
   - `EHRRecord` Pydantic model

1.4 Create `backend/app/services/knowledge_base.py`:
   - `build_knowledge_base() -> None` — reads `rare_disease_profiles.json`, embeds each profile document, persists to `data/chroma_db/`
   - `search_by_fingerprint(hpo_ids: list[str], trigger_texts: list[str], ehr_conditions: list[str], top_k: int = 5) -> list[RareDiseaseProfile]` — builds query string, embeds, retrieves top-K
   - `get_all_profiles() -> list[RareDiseaseProfile]` — for validation
   - Use `sentence-transformers` local embedding by default; switch to `text-embedding-3-small` when `OPENAI_API_KEY` is present
   - Persist ChromaDB at `backend/data/chroma_db/`; rebuild if collection is empty

1.5 Write `backend/tests/test_knowledge_base.py`:
   - Knowledge base builds without error
   - Search returns ≤top_k results
   - POTS query (`HP:0001649`, `HP:0002907`, trigger="standing") retrieves POTS profile in top-3
   - hEDS query (`HP:0001382`, `HP:0002829`) retrieves hEDS profile in top-3
   - MCAS query (`HP:0001025`, `HP:0002018`, dietary triggers) retrieves MCAS in top-3

---

## Group 2 — EHR Connection (Medblocks Patient Access)

**Goal:** Full patient EHR connection flow using Medblocks hosted auth page; FHIR records pulled and stored.

2.1 Create Alembic migration for two new tables:

   `ehr_connections`:
   ```sql
   id (uuid pk), patient_id (text), medblocks_patient_id (text),
   connection_status (text), connected_at (timestamptz),
   fhir_resource_counts (jsonb default '{}'), last_synced_at (timestamptz),
   created_at (timestamptz)
   ```

   `ehr_records`:
   ```sql
   id (uuid pk), patient_id (text), resource_type (text),
   resource_id (text), resource_json (jsonb), synced_at (timestamptz),
   UNIQUE(patient_id, resource_type, resource_id)
   ```

2.2 Create `backend/app/services/ehr_reader.py`:
   - `start_patient_session(patient_id: str, return_url: str) -> str` — calls Medblocks API `POST /patient-sessions`, returns `auth_url`
   - `verify_patient_session(patient_session_id: str) -> dict` — calls `GET /patient-sessions/{id}`
   - `get_connections(patient_id: str) -> list[dict]` — calls `GET /patients/{id}` and returns connections list
   - `pull_fhir_records(patient_id: str, resource_types: list[str]) -> dict[str, list[dict]]` — paginated `GET /patients/{id}/records`, returns records grouped by resource type
   - Note: Use `httpx.AsyncClient` with Medblocks bearer token; follow Medblocks skill's pagination pattern (`has_more`, `next_cursor`, `starting_after`)
   - Resource types to pull: `Condition`, `Observation`, `MedicationRequest`, `AllergyIntolerance`, `Encounter`

2.3 Create `backend/app/routers/ehr.py`:
   ```
   POST /ehr/connect/start
     Body: { patient_id, return_url }
     Returns: { auth_url }

   POST /ehr/connect/complete
     Body: { patient_id, patient_session_id }
     Verifies session → gets connections → returns { connection_status }

   POST /ehr/sync
     Body: { patient_id }
     Triggers paginated FHIR pull → upserts into ehr_records table
     Returns: { synced_counts: { Condition: N, Observation: N, ... } }

   GET /ehr/status
     Query: ?patient_id=...
     Returns: EHRConnection shape
   ```

2.4 Wire router into `main.py`.

2.5 Create `backend/app/routers/ehr_return/page.tsx` (frontend — Next.js):
   - Route: `/ehr/connected`
   - Reads `?patient_id=...&patient_session_id=...` from URL
   - Calls `POST /api/ehr/connect/complete` → shows success/pending/error state
   - If success: calls `POST /api/ehr/sync` → shows syncing spinner → shows resource counts
   - Links back to check-in home

2.6 Add EHR connection button to frontend homepage:
   - "Connect your health records" CTA → calls `POST /api/ehr/connect/start` → redirects to `auth_url`

2.7 Write `backend/tests/test_ehr_reader.py` (all Medblocks API calls mocked):
   - `start_patient_session` returns auth_url
   - `verify_patient_session` returns session dict
   - `pull_fhir_records` paginates correctly (tests `has_more=True` path)
   - `pull_fhir_records` handles empty result (no records yet)
   - Upsert idempotency: same resource_id written twice → one row

---

## Group 3 — Hypothesis Surfacer Node

**Goal:** LangGraph node that runs the RAG-based hypothesis analysis.

3.1 Create `backend/app/agents/hypothesis_node.py`:
   - System prompt: role, HPO context, output schema, guardrails (NO diagnosis language, NO "you have/might have", mandatory uncertainty framing)
   - `build_symptom_fingerprint(patient_id: str) -> dict` — reads last 90 days of FHIR Observations from Medblocks for patient, extracts HPO IDs, trigger texts, severity patterns
   - `build_ehr_context(patient_id: str) -> dict` — reads EHR records from PostgreSQL `ehr_records` table; extracts Condition names, key Observations (abnormal labs), Medication names
   - `hypothesis_node(state: HypothesisState) -> dict` — builds fingerprint + EHR context → searches ChromaDB for top-5 → constructs prompt with retrieved profiles → calls Claude Sonnet → parses `HypothesisReport`
   - Strips markdown fences from LLM output before parsing
   - Validates all `HypothesisProfile` entries: `discuss_with_specialist` must be `True` (enforced by schema, not trusted from LLM)
   - Appends hardcoded `guardrail_disclosure` after LLM output — not LLM-generated

3.2 Create `backend/app/agents/hypothesis_graph.py`:
   - `HypothesisState` TypedDict: `patient_id`, `symptom_fingerprint`, `ehr_context`, `retrieved_profiles`, `hypothesis_report`, `human_approved`, `status`, `errors`
   - `StateGraph` with nodes: `hypothesis_node`, `review_gate` (no-op HITL)
   - `interrupt_before=["review_gate"]` — patient reviews before report is accessible via API
   - `route_after_review`: `"approved"` → END; `"rejected"` → `hypothesis_node` (with feedback for regeneration)

3.3 Create `backend/app/routers/hypothesis.py`:
   ```
   POST /hypothesis/start
     Body: { patient_id }
     Returns: { session_id, status, min_observations_required, observations_available }
     Returns 422 if observations_available < 30 (gate check)

   GET /hypothesis/{id}/status

   GET /hypothesis/{id}/report
     Returns full HypothesisReport (only after human_approved=True)

   POST /hypothesis/{id}/approve
     Body: { decision: "approve" | "regenerate", feedback? }
     Returns: { status }
   ```

3.4 Wire hypothesis router into `main.py`.

3.5 Write `backend/tests/test_hypothesis_node.py` (mocked LLM + ChromaDB):
   - Guardrail: `"you have"`, `"you might have"`, `"diagnosis"` never appear in hypothesis profiles
   - `discuss_with_specialist` is always `True` regardless of LLM output
   - `guardrail_disclosure` is always appended
   - POTS fingerprint retrieves POTS as top hypothesis
   - 30-observation gate blocks hypothesis when observations < 30

---

## Group 4 — Frontend Hypothesis UI

**Goal:** Hypothesis results page showing ranked profiles with plain-language explanations.

4.1 Create `frontend/src/app/hypothesis/page.tsx`:
   - Checks if patient has ≥30 observations (from API) → shows unlock progress if not
   - "Analyse my pattern" CTA → calls `POST /api/hypothesis/start` → polling `/status`
   - Shows loading state with message: "Comparing your symptom pattern against rare disease profiles…"
   - Once complete: shows `HypothesisReport` results

4.2 Create `frontend/src/components/HypothesisCard.tsx`:
   - One card per hypothesis profile
   - Shows: condition name, match strength badge (colour-coded), matching symptoms list, missing signals, plain language explanation
   - "Ask your specialist about this" CTA → links to appointment prep (Phase 1 feature)
   - Guardrail disclosure shown prominently at bottom

4.3 Create `frontend/src/components/EHRConnectionStatus.tsx`:
   - Shows current connection status ("Not connected", "Connected — N records synced", "Syncing…")
   - "Connect records" CTA when not connected
   - Note: "Connecting your health records improves pattern analysis"

4.4 Add navigation link to hypothesis page from homepage.

---

## Group 5 — Integration + End-to-End Tests

5.1 Write `backend/tests/test_hypothesis_api.py`:
   - Full flow: `POST /hypothesis/start` → `GET /status` → `POST /approve` → `GET /report`
   - Gate returns 422 when < 30 observations
   - Report not accessible before approval (returns 409)
   - Guardrail disclosure present in every report

5.2 Write `backend/tests/test_ehr_api.py`:
   - Full EHR connection flow mocked end-to-end
   - Sync idempotency: calling sync twice doesn't duplicate records

5.3 Manual E2E checklist (run against Medblocks sandbox):
   - Start EHR connection → verify Medblocks hosted page opens
   - Complete auth → verify return page parses correctly
   - Trigger sync → verify resource counts appear
   - Run hypothesis (seed 30 check-in observations) → verify top hypothesis is relevant

5.4 Update GitHub Actions CI to include new test files.
