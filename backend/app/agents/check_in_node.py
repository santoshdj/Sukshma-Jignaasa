"""
Check-In AI Node
----------------
Claude Haiku (via LiteLLM) processes one conversational turn:
  - Extracts structured symptom fields from patient free-text
  - Maps symptoms to HPO terms from the curated vocabulary
  - Applies adaptive tone (brief / gentle / engaged)
  - Decides when sufficient signal has been captured
  - Produces a running CheckInExtraction updated each turn

Output per turn (JSON):
  {
    "message": "<AI response to patient>",
    "is_complete": false,
    "tone_used": "engaged",
    "extraction": { ...CheckInExtraction fields... }
  }
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from app.models.check_in import CheckInExtraction, CheckInState
from app.services.llm_service import get_check_in_llm

logger = logging.getLogger(__name__)

# ── HPO vocabulary for the prompt (most clinically relevant ~60 terms) ────────

_HPO_VOCAB_PATH = Path(__file__).resolve().parents[2] / "app" / "data" / "hpo_terms.json"

def _load_prompt_vocabulary() -> str:
    with _HPO_VOCAB_PATH.open("r", encoding="utf-8") as f:
        terms = json.load(f)
    lines = [f"  {t['hpo_id']}  {t['label']}  [{t['body_system']}]" for t in terms]
    return "\n".join(lines)


_HPO_VOCAB_STR = _load_prompt_vocabulary()

# ── Tone detection ────────────────────────────────────────────────────────────

_PAIN_SIGNALS = re.compile(
    r"\b(crash|exhausted|terrible|awful|can't|couldn't|struggle|bad|rough|horrible|severe)\b",
    re.IGNORECASE,
)
_ENGAGED_SIGNALS = re.compile(
    r"\b(also|and|because|think|noticed|wonder|usually|pattern|always|after)\b",
    re.IGNORECASE,
)

def _detect_tone(patient_message: str) -> str:
    if len(patient_message.strip()) < 20:
        return "brief"
    if _PAIN_SIGNALS.search(patient_message):
        return "gentle"
    if _ENGAGED_SIGNALS.search(patient_message):
        return "engaged"
    return "engaged"


# ── Guardrail check ───────────────────────────────────────────────────────────

_GUARDRAIL_PATTERNS = [
    re.compile(r"\bdiagnos(is|e|ed|ing)\b", re.IGNORECASE),
    re.compile(r"\bthis could (be|indicate|suggest|mean)\b", re.IGNORECASE),
    re.compile(r"\byou (might|may|could) have\b", re.IGNORECASE),
    re.compile(r"\bI (think|believe|suspect)\b", re.IGNORECASE),
    re.compile(r"\bsounds(\s+\w+)?\s+(serious|concerning|worrying|alarming)\b", re.IGNORECASE),
    re.compile(r"\bcould be\b", re.IGNORECASE),
]

def check_guardrails(text: str) -> list[str]:
    """Return list of violated guardrail pattern descriptions (empty = clean)."""
    violations = []
    for pattern in _GUARDRAIL_PATTERNS:
        if pattern.search(text):
            violations.append(pattern.pattern)
    return violations


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = f"""You are a gentle, adaptive AI companion for a patient who is tracking their health symptoms to help identify patterns. Your job is to have a brief, warm conversation to capture today's health observations in a structured format.

## Your role
You are NOT a doctor. You do NOT interpret what symptoms mean. You ONLY help the patient log observations accurately.

## Guardrails — you must NEVER:
- Use the word "diagnosis" or "diagnose"
- Say "this could be", "you might have", "that could indicate"
- Interpret what a symptom might mean clinically
- Express alarm or concern about severity ("that sounds serious")
- Recommend any action, medication, or test
- Redirect emergencies — if a patient mentions chest pain + shortness of breath + arm pain together, simply say: "Please call emergency services if you feel this is urgent."

## Conversation rules
- Maximum 8 exchanges total. Be efficient.
- Brief mode (short patient messages): ≤30 words per response
- Gentle mode (patient mentions pain/crash): ≤25 words, warm acknowledgement first
- Engaged mode (patient gives detail): ≤50 words, one follow-up question
- ALWAYS end the conversation yourself when you have: at least one symptom OR a no-symptom declaration, plus any context available
- On a no-symptom day: acknowledge warmly, ask ONE follow-up about energy/sleep, then mark complete
- NEVER comment on how serious a symptom sounds

## HPO Vocabulary (use ONLY these IDs — never invent HPO codes)
{_HPO_VOCAB_STR}

## Output format
Respond with a single valid JSON object — no markdown fences, no extra text:
{{
  "message": "<your conversational response to the patient — plain text, no JSON>",
  "is_complete": false,
  "tone_used": "brief|gentle|engaged",
  "extraction": {{
    "symptoms": [
      {{
        "symptom_text": "<verbatim or close paraphrase of what patient said>",
        "hpo_terms": [
          {{"hpo_id": "HP:XXXXXXX", "label": "<label>", "confidence": "high|medium|low"}}
        ],
        "body_system": "<neurological|musculoskeletal|cardiovascular|autonomic|gastrointestinal|immunological|dermatological|endocrine|respiratory|other>",
        "severity": <1-10>,
        "duration_minutes": <null or int>,
        "onset_time": <null or ISO datetime string>,
        "probable_trigger": <null or string>,
        "trigger_delay_minutes": <null or int>,
        "sleep_quality": <null or 1-10>,
        "activity_level": <null or "low|moderate|high">,
        "stress_level": <null or 1-10>,
        "dietary_notes": <null or string>,
        "cycle_phase": <null or "follicular|ovulatory|luteal|menstrual|not_applicable|unknown">
      }}
    ],
    "is_no_symptom_day": false,
    "session_notes": "<brief internal note, not shown to patient>",
    "tone_used": "brief|gentle|engaged"
  }}
}}

Set "is_complete": true when you have enough information and are ready to show the patient a summary for confirmation.
"""

# ── Stripping helpers ─────────────────────────────────────────────────────────

def _strip_fences(raw: str | list) -> str:
    # Claude occasionally returns content as a list of blocks — flatten to text.
    if isinstance(raw, list):
        raw = " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in raw
        )
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


# ── Opening message generator ─────────────────────────────────────────────────

_OPENING_WITH_QUICK_LOG = (
    "Thanks for logging those — anything you'd like to add? "
    "Triggers, context, or anything else worth noting?"
)
_OPENING_NO_QUICK_LOG = "How are you feeling today? Start with whatever feels most noticeable."
_OPENING_NO_SYMPTOM_PROMPT = (
    "Good to hear! Anything about your energy or sleep worth noting for your records?"
)


# ── Main node ─────────────────────────────────────────────────────────────────

def check_in_node(state: CheckInState) -> dict:
    """
    Process one turn of the check-in conversation.
    Reads the latest user message from conversation_history,
    calls Claude Haiku, returns updated state fields.
    """
    history = state.get("conversation_history", [])
    turn_count = state.get("turn_count", 0)
    quick_log = state.get("quick_log_entries", [])

    # ── Opening turn (no user message yet) ────────────────────────────────────
    if not history or history[-1]["role"] == "assistant":
        if turn_count == 0:
            opening = _OPENING_WITH_QUICK_LOG if quick_log else _OPENING_NO_QUICK_LOG
            new_history = list(history) + [{"role": "assistant", "content": opening}]
            return {
                "conversation_history": new_history,
                "turn_count": 1,
                "status": "in_progress",
            }

    # ── Safety: enforce max turns ──────────────────────────────────────────────
    if turn_count >= 8:
        logger.info("check_in_node: max turns reached, forcing completion")
        current_extraction = state.get("current_extraction") or {}
        return {
            "current_extraction": current_extraction,
            "status": "awaiting_confirmation",
        }

    # ── Build LLM messages ─────────────────────────────────────────────────────
    llm = get_check_in_llm()
    patient_message = history[-1]["content"] if history and history[-1]["role"] == "user" else ""
    tone = _detect_tone(patient_message)

    context_parts = []
    if quick_log:
        ql_summary = "; ".join(
            f"{e.get('symptom_name', 'unknown')} severity {e.get('severity', '?')}/10"
            for e in quick_log
        )
        context_parts.append(f"Quick-log already recorded: {ql_summary}")
    if turn_count > 1 and state.get("current_extraction"):
        context_parts.append(
            f"Extraction so far: {json.dumps(state['current_extraction'], default=str)}"
        )

    context_note = "\n".join(context_parts)
    turn_note = f"Turn {turn_count + 1}/8. Tone: {tone}."
    full_system = _SYSTEM_PROMPT
    if context_note:
        full_system += f"\n\n## Current session context\n{context_note}\n{turn_note}"
    else:
        full_system += f"\n\n{turn_note}"

    lc_messages = [SystemMessage(content=full_system)]
    for msg in history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            lc_messages.append(HumanMessage(content=content))
        else:
            from langchain_core.messages import AIMessage
            lc_messages.append(AIMessage(content=content))

    # ── Call LLM (with one retry on empty / unparseable response) ─────────────
    parsed: dict | None = None
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            response = llm.invoke(lc_messages)
            raw = _strip_fences(response.content)
            if not raw:
                logger.warning(
                    "check_in_node attempt %d: empty content after stripping — "
                    "raw repr: %r  additional_kwargs: %r  metadata: %s",
                    attempt + 1,
                    response.content,
                    getattr(response, "additional_kwargs", {}),
                    getattr(response, "response_metadata", {}),
                )
                raise ValueError("LLM returned empty response")
            parsed = json.loads(raw)
            break  # success
        except Exception as exc:
            last_exc = exc
            if attempt == 0:
                logger.warning("check_in_node attempt 1 failed (%s), retrying…", exc)
            else:
                logger.error("check_in_node LLM call failed after retry: %s", exc)

    if parsed is None:
        fallback_msg = "I'm having a moment — can you say that again?"
        new_history = list(history) + [{"role": "assistant", "content": fallback_msg}]
        return {
            "conversation_history": new_history,
            "turn_count": turn_count + 1,
            "errors": state.get("errors", []) + [f"LLM error turn {turn_count}: {last_exc}"],
            "status": "in_progress",
        }

    ai_message: str = parsed.get("message", "")
    is_complete: bool = parsed.get("is_complete", False)
    extraction_dict: dict = parsed.get("extraction", {})
    tone_used: str = parsed.get("tone_used", tone)

    # Guardrail check
    violations = check_guardrails(ai_message)
    if violations:
        logger.warning("Guardrail violation(s) in check_in_node: %s", violations)
        ai_message = "Let me rephrase that. Can you tell me more about what you're experiencing?"

    # Validate HPO IDs (strip any hallucinated codes)
    from app.models.check_in import VALID_HPO_IDS
    for symptom in extraction_dict.get("symptoms", []):
        symptom["hpo_terms"] = [
            t for t in symptom.get("hpo_terms", [])
            if t.get("hpo_id") in VALID_HPO_IDS
        ]

    new_history = list(history) + [{"role": "assistant", "content": ai_message}]
    new_status = "awaiting_confirmation" if is_complete else "in_progress"

    return {
        "conversation_history": new_history,
        "turn_count": turn_count + 1,
        "current_extraction": extraction_dict,
        "tone_mode": tone_used,
        "status": new_status,
    }
