# Mission — Sukshma-Jignaasa

**सूक्ष्म जिज्ञासा** — *Subtle Inquiry*

Sukshma-Jignaasa exists because the rare disease patient is alone.

The average rare disease patient sees 7 specialists over 4–7 years before receiving a diagnosis. In that time they fill out the same intake forms from scratch at every appointment, reconstruct their symptom history from memory, and watch their clinicians treat each visit as isolated — disconnected from the pattern that is slowly becoming visible only to the person living it.

No EHR tracks what the patient notices between appointments. No tool connects the fatigue that spikes two days after exertion, the joint pain that always arrives with the brain fog, the GI episodes that cluster around hormonal cycles. The patient sees this pattern. The system does not.

Sukshma-Jignaasa is the AI companion that closes this gap. It gives the undiagnosed patient the tools to document, surface, and communicate the subtle patterns that the medical system is not designed to see.

---

## What It Does

The app operates in two phases across a patient's diagnostic journey:

### Phase 1 — The Diagnostic Companion (Undiagnosed)

A self-advocate who suspects a rare or complex condition uses the app as a longitudinal symptom intelligence tool:

- **Daily hybrid logging** — a one-tap quick-log for known symptoms (severity, duration) plus a brief AI-led check-in conversation that captures triggers, context (sleep, activity, food, stress, menstrual cycle), and free-text observations. Structured fields are extracted automatically; the patient never fills a form.

- **Pattern Narrator** — the AI surfaces temporal and co-occurrence patterns across the logged history: symptom clusters, trigger correlations, progression trajectories. Updated continuously as new data arrives. Framed as observations, never conclusions.

- **Hypothesis Surfacer** — after sufficient data accumulates, the AI identifies which rare disease profiles the patient's symptom fingerprint most resembles. Each hypothesis is presented with explicit uncertainty, a plain-language explanation of the match, and a mandatory prompt to discuss with a specialist. This is a research starting point, not a diagnosis.

- **Appointment Preparation** — before a scheduled appointment, the AI generates a structured pre-visit summary: the top symptoms by frequency and severity, the timeline of progression, the most relevant co-occurrences, and a suggested list of questions to raise with the clinician. The patient reviews and approves before anything is shared.

### Phase 2 — The Monitoring Companion (Post-Diagnosis)

Once a diagnosis is confirmed, the app transitions:

- Symptom tracking becomes disease-specific — calibrated to the confirmed condition's known activity markers
- Care plan milestones and medication logging are added
- EHR connection via Medblocks enables direct FHIR data pull from the patient's connected health systems
- Disease progression summaries replace diagnostic hypothesis surfacing

---

## Who It Serves

**Primary user (Phase 1):** The self-advocate, undiagnosed adult. Typically 25–45 years old. Managing multi-system symptoms — fatigue, pain, autonomic dysfunction, cognitive fog, GI involvement — that no single specialist has been able to explain. High health literacy. Already doing their own research. Exhausted by the system but not defeated by it.

Conditions this persona commonly lands on after years of investigation: hypermobile Ehlers-Danlos Syndrome (hEDS), Postural Orthostatic Tachycardia Syndrome (POTS), Mast Cell Activation Syndrome (MCAS), autoimmune overlap syndromes, rare mitochondrial disorders, unclassified connective tissue diseases.

**Secondary user (Phase 2):** A diagnosed rare disease patient managing a chronic condition with a known specialist team.

---

## What Success Looks Like

A patient who has spent three years unable to explain their symptom pattern to a new specialist can, after 60 days with Sukshma-Jignaasa, walk into that appointment with a structured timeline, a set of AI-identified correlations, and a prioritised list of questions — and leave the appointment with a referral instead of another dead end.

The app does not diagnose. It organises, surfaces, and communicates. The diagnosis happens between the patient and their clinician. Sukshma-Jignaasa makes that conversation possible.

---

## What It Is Not

- **Not a diagnostic tool.** No output from this app constitutes a medical diagnosis. All pattern observations and hypothesis profiles are informational and must be discussed with a qualified clinician.
- **Not a medical device.** The app is positioned as a wellness and personal health information tool. It does not interpret lab results, recommend medications, or make clinical decisions.
- **Not an emergency service.** The app will never serve as a substitute for emergency care. All crisis or emergency scenarios are redirected immediately to emergency services (911/112).

---

## Design Principles

1. **The patient is the expert on their own body.** The AI is a pattern-finding assistant, not an authority. The patient always reviews and approves before anything is shared with a clinician.
2. **Longitudinal over episodic.** A single symptom report is noise. Patterns over weeks and months are signal. Every design decision optimises for sustained daily engagement.
3. **Uncertainty is honest.** Confidence scores, uncertainty language, and "discuss with your specialist" prompts are not legal disclaimers — they are the correct representation of what the AI knows and does not know.
4. **Privacy is structural.** Clinical data is stored as pseudonymised FHIR resources. No identifying information is required to use the core logging and pattern features. Patients control what gets shared and with whom.
5. **The system is the spec.** Every AI mode, prompt, and guardrail is specified before it is built. Behaviour is observable, testable, and auditable.
