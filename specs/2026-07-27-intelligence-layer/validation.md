# Validation — Phase 2: The Intelligence Layer

---

## Automated Tests

### Unit + Integration Tests

| Test file | What is asserted |
|-----------|-----------------|
| `tests/test_knowledge_base.py` | ChromaDB builds without error; POTS/hEDS/MCAS queries retrieve correct profiles in top-3; empty query handles gracefully |
| `tests/test_ehr_reader.py` | Session start/verify work with mocked Medblocks API; pagination (has_more=True) traversed correctly; empty records handled; upsert idempotency verified |
| `tests/test_hypothesis_node.py` | Guardrail patterns absent in all outputs; discuss_with_specialist always True; guardrail_disclosure always appended; 30-obs gate enforced |
| `tests/test_hypothesis_api.py` | Full flow state machine; report not accessible before approval; 422 when < 30 observations |
| `tests/test_ehr_api.py` | Full EHR connection flow mocked; sync idempotency |

### Mandatory Guardrail Assertions (added to hypothesis tests)

```python
HYPOTHESIS_PROHIBITED = [
    re.compile(r"\byou (have|likely have|probably have)\b", re.IGNORECASE),
    re.compile(r"\bdiagnos(is|e|ed|ing)\b", re.IGNORECASE),
    re.compile(r"\bthis is consistent with\b", re.IGNORECASE),
    re.compile(r"\bthis (could|may|might) be\b", re.IGNORECASE),
    re.compile(r"\bI (believe|think|suspect)\b", re.IGNORECASE),
]

REQUIRED_IN_EVERY_REPORT = [
    "discuss_with_specialist",     # must be True in all HypothesisProfile entries
    "guardrail_disclosure",        # must be non-empty string in HypothesisReport
]
```

### Knowledge Base Retrieval Scenarios (test fixtures)

| Scenario | Query HPO IDs | Query triggers | Expected top condition |
|----------|--------------|----------------|----------------------|
| POTS | HP:0001649, HP:0002321, HP:0012758 | prolonged standing | POTS |
| hEDS | HP:0001382, HP:0002829, HP:0001388 | joint dislocations | hEDS |
| MCAS | HP:0001025, HP:0002018, HP:0030214 | food, fragrance | MCAS |
| hEDS+POTS+MCAS | All above combined | multiple | hEDS as #1, POTS #2, MCAS #3 |
| Vague input (few HPO terms) | HP:0012378 only | none | Returns ≤5 results, no error |

---

## Manual Walkthrough

### EHR Connection Flow

1. Open frontend → tap "Connect your health records"
2. Frontend calls `POST /api/ehr/connect/start` → receives `auth_url`
3. Browser redirects to Medblocks hosted page
4. Patient selects EHR provider and completes OAuth
5. Patient lands on `/ehr/connected?patient_id=...&patient_session_id=...`
6. Frontend calls `POST /api/ehr/connect/complete` → status shows "Connected"
7. Frontend calls `POST /api/ehr/sync` → syncing spinner → resource counts displayed
   - Expected: `{ Condition: N, Observation: N, MedicationRequest: N, ... }`
8. Navigate to hypothesis page → EHR connection badge shows "Connected — N records synced"

### Hypothesis Flow (requires ≥30 check-in observations seeded)

1. Open hypothesis page → check observation count
2. If < 30: progress bar shown ("28/30 check-ins logged")
3. If ≥ 30: "Analyse my pattern" button visible
4. Tap button → loading state: "Comparing your symptom pattern against rare disease profiles…"
5. Results appear: 3–5 hypothesis cards ranked high → medium → low
6. Each card shows: condition name, match strength, matching symptoms, missing signals, plain explanation
7. Guardrail disclosure visible below all cards
8. Patient taps "Looks right" → report approved → "Ask your specialist" CTAs activate
9. Patient can tap "Regenerate" → enters feedback → new analysis runs

### Edge Cases

| Edge case | Expected behaviour |
|-----------|-------------------|
| EHR connected but records not yet available | `/ehr/status` shows `connection_status: "pending"`, `fhir_resource_counts: {}`. Frontend shows "Records syncing — check back in a few minutes" |
| Patient connects EHR again (re-auth) | `ehr_connections` row updated (upsert); `ehr_records` upserted idempotently |
| Hypothesis run with only check-in data (no EHR) | Runs successfully; `ehr_records_included: false` in report; note shown to patient: "Connect your health records for a more complete analysis" |
| < 30 observations | `POST /hypothesis/start` returns 422 with `{ observations_available: N, min_required: 30 }` |
| LLM returns diagnosis language | Guardrail check strips/replaces before saving; logged as warning |
| ChromaDB collection missing | `build_knowledge_base()` runs on first hypothesis request; subsequent requests hit cache |
| EHR sync fails mid-pagination | Already-written records kept (idempotent upsert); error logged; partial sync counts returned |

---

## Security & Privacy Checks

- [ ] `MEDBLOCKS_API_KEY` never logged or returned in API responses
- [ ] Raw FHIR resources not logged at INFO level (DEBUG only, behind flag)
- [ ] `ehr_records.resource_json` never included in error messages
- [ ] Hypothesis reports contain no PHI beyond HPO labels and condition names
- [ ] `guardrail_disclosure` is hardcoded in backend — never overridable by LLM output
- [ ] ChromaDB persistence directory excluded from git (`.gitignore`)
- [ ] Medblocks patient session verification is server-side (`patientSession.retrieve`) — never trusted from browser query params alone

---

## Definition of Done

All of the following must be true before Phase 2 is marked complete in `specs/ROADMAP.md`:

- [ ] All automated tests pass (`uv run pytest tests/ -v`)
- [ ] All guardrail assertions pass for all hypothesis scenarios
- [ ] `discuss_with_specialist: True` in every HypothesisProfile in every test
- [ ] `guardrail_disclosure` present and non-empty in every HypothesisReport
- [ ] Knowledge base retrieval scenarios pass (POTS/hEDS/MCAS in expected top positions)
- [ ] EHR connection flow verified manually against Medblocks sandbox
- [ ] FHIR records sync verified (at least one resource type populated in `ehr_records`)
- [ ] Hypothesis flow verified end-to-end with ≥30 seeded observations
- [ ] Frontend type-check passes (`bunx tsc --noEmit`)
- [ ] No PHI in any server log or error message
- [ ] `data/chroma_db/` added to `.gitignore`
- [ ] `specs/2026-07-27-intelligence-layer/meta.json` written
