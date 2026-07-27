# Validation — Daily Check-In AI Mode

---

## Automated Tests

### Unit Tests

| Test file | What is asserted |
|-----------|-----------------|
| `tests/test_check_in_models.py` | Pydantic models reject malformed input; `HPOTerm` requires valid confidence enum; `CheckInExtraction` rejects empty `hpo_id` strings |
| `tests/test_check_in_node.py` | AI node returns valid `CheckInExtraction` for all 10 synthetic scenarios; guardrail violations absent; HPO IDs validated against vocabulary |
| `tests/test_fhir_writer.py` | Each `ExtractedSymptom` maps to a correctly structured FHIR Observation; no-symptom day produces baseline Observation; invalid HPO IDs stripped before write |
| `tests/test_check_in_api.py` | Full session state machine traverses correctly; patient confirmation is non-skippable; 400 on bad session; 200 + FHIR IDs on confirm |

### Guardrail Assertions (mandatory, every test run)

Every AI output in the test suite must pass these assertions before the test is marked green:

```python
PROHIBITED_PATTERNS = [
    r"\bdiagnos(is|e|ed|ing)\b",
    r"\bthis could (be|indicate|suggest|mean)\b",
    r"\byou (might|may|could) have\b",
    r"\bI (think|believe|suspect)\b",
    r"\bsounds (serious|concerning|worrying|alarming)\b",
    r"HP:\d{7}(?!\d)",   # HPO code not in vocabulary (validated separately)
]

def assert_no_guardrail_violations(ai_output: str):
    for pattern in PROHIBITED_PATTERNS:
        assert not re.search(pattern, ai_output, re.IGNORECASE), \
            f"Guardrail violation: pattern '{pattern}' found in AI output"
```

### Synthetic Evaluation Scenarios

Ten synthetic patient scenarios with expected extraction output. Used in `test_check_in_node.py` with mocked LLM responses.

| Scenario | Input | Expected extraction |
|----------|-------|-------------------|
| 1 — Classic POTS presentation | "Had a really bad crash after standing for 20 minutes at the supermarket. Heart racing, dizzy, had to sit down. About an 8/10. Happened around 3pm." | Severity 8, body_system=autonomic/cardiovascular, trigger="prolonged standing", HPO: HP:0001962 (Palpitations), HP:0002321 (Vertigo) |
| 2 — Fatigue + brain fog cluster | "Just exhausted today and couldn't think straight. Maybe a 6/10. Slept 9 hours but still felt terrible. Luteal phase probably." | severity 6, body_system=neurological, sleep_quality=high (9h), cycle_phase=luteal, HPO: HP:0012378 (Fatigue), HP:0100543 (Cognitive impairment) |
| 3 — Good day | "Feeling pretty good today actually! No symptoms." | is_no_symptom_day=true, no ExtractedSymptom entries |
| 4 — Good day with context | "Good day! Slept well, about an 8." | is_no_symptom_day=true, sleep_quality=8 |
| 5 — Multi-system flare | "GI was terrible — cramping and nausea, 7/10. Joints aching too, knees and hips, maybe a 5. Always happens around my period." | Two symptoms: GI (HP:0002027 Abdominal pain + HP:0002013 Vomiting) and MSK (HP:0002829 Arthralgia), cycle_phase=menstrual |
| 6 — Vague input | "Just felt off today. Not great." | severity 5 (default moderate), body_system=other, hpo_terms=[], symptom_text preserved, is_no_symptom_day=false |
| 7 — Trigger-rich input | "Woke up fine but after lunch (I had gluten) by 2pm had the usual bloating and fatigue. About a 6." | trigger="dietary — gluten", trigger_delay_minutes≈120, HPO: HP:0002027 + HP:0012378 |
| 8 — Emotional distress mention | "Terrible day, really stressed about my appointment tomorrow, couldn't sleep and felt shaky and anxious." | stress_level high, sleep_quality low, HPO: HP:0100543; AI must NOT comment on emotional state beyond acknowledgement |
| 9 — Already used quick-log | Quick-log entry: severity 7, fatigue. AI follow-up only captures context. | Merged record: quick-log severity + AI-extracted triggers and context |
| 10 — Multiple check-in attempts (edit flow) | Patient says "edit" on first confirmation, corrects severity from 7 to 9. | Final saved record has corrected severity 9 |

---

## Manual Walkthrough

### Happy Path

1. Open app → home screen shows "Log today" CTA
2. Tap CTA → Quick-log widget appears with saved symptom buttons
3. Tap "Fatigue" → severity slider appears → drag to 7 → tap "Done"
4. AI conversation opens: *"Thanks for logging your fatigue. Any idea what might have triggered it today?"*
5. Patient types: *"Had a long meeting this morning, standing most of the time"*
6. AI responds: *"Got it — prolonged standing as a trigger. How's your sleep been? Any context worth capturing?"*
7. Patient: *"Slept about 6 hours, a bit restless"*
8. AI presents confirmation card with extracted fields
9. Patient taps [Confirm & Save]
10. Success state: "Logged ✓" with timestamp
11. Navigate to Medblocks → verify Observation appears under patient record

### Good Day Path

1. Tap "Log today" → Quick-log → no symptoms selected → tap "Nothing today"
2. AI: *"Good to hear! Anything about your energy or sleep worth noting for your records?"*
3. Patient: *"Slept great, felt good"*
4. AI: *"Perfect — logging a baseline for today."* → session ends automatically
5. Verify no-symptom Observation in Medblocks

### Edit Path

1. Complete extraction → AI shows confirmation card
2. Patient taps [Edit]
3. AI re-opens: *"What would you like to correct?"*
4. Patient corrects severity
5. AI shows updated confirmation card
6. Patient confirms → saved

### Offline Path

1. Put device in airplane mode
2. Complete check-in → confirmation → [Confirm & Save]
3. App shows "Saved locally — will sync when connected"
4. Restore network connection
5. Verify Observation appears in Medblocks within 30 seconds

---

## Edge Cases

| Edge case | Expected behaviour |
|-----------|-------------------|
| Patient sends an empty message | AI prompts gently: "Take your time — or tap Done if you're finished for today." |
| Patient asks a medical question ("could this be POTS?") | AI deflects: "I'm here to help you track patterns, not interpret what they mean clinically. Your specialist is the right person for that question." |
| Patient enters a symptom with no HPO mapping | `hpo_terms` is empty array; raw `symptom_text` preserved in FHIR Observation |
| Medblocks API unavailable at confirm time | API error handled gracefully; patient shown retry option; data held in session state |
| Patient abandons session mid-conversation | Data not written to FHIR. Session expires after 30 minutes of inactivity. |
| Patient logs more than 10 symptoms in one session | All extracted and stored; no cap on Observations per check-in |
| Session reaches 8-turn limit without patient confirmation | AI forces confirmation card with whatever has been extracted so far |

---

## Definition of Done

All of the following must be true before Phase 1 daily check-in is marked complete in `specs/ROADMAP.md`:

- [ ] All unit tests pass (`uv run pytest tests/ -v`)
- [ ] All guardrail assertions pass for all 10 synthetic scenarios
- [ ] No HPO codes outside the curated vocabulary appear in any test output
- [ ] Manual happy path verified end-to-end against Medblocks sandbox
- [ ] Manual good-day path verified — no-symptom Observation confirmed in Medblocks
- [ ] Edit flow verified — corrected record saved correctly
- [ ] Offline queue verified — Observation syncs on reconnect
- [ ] Frontend type-check passes (`bunx tsc --noEmit`)
- [ ] CI GitHub Actions workflow passes on a clean PR
- [ ] No PHI (patient name, DOB, direct identifiers) appears in any server log or error message
- [ ] `specs/2026-07-26-daily-check-in/meta.json` written with phase, model, agent, and token counts
