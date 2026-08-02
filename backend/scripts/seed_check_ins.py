"""
seed_check_ins.py — Seed symptom check-ins and optionally trigger hypothesis analysis.

Usage:
    python scripts/seed_check_ins.py                  # 5 sessions
    python scripts/seed_check_ins.py --count 35       # 35 sessions (enough for hypothesis)
    python scripts/seed_check_ins.py --count 35 --hypothesis  # 35 + run hypothesis
    python scripts/seed_check_ins.py --base-url http://localhost:8000

The script drives the full check-in conversation loop for each session:
    POST /check-in/start → POST /check-in/message (repeat) → POST /check-in/confirm
"""

from __future__ import annotations

import argparse
import re
import random
import sys
import time
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_PATIENT_ID = "patient-demo-001"
MAX_TURNS_PER_SESSION = 6  # safety cap — AI usually reaches confirmation in 2-3 turns
REQUEST_TIMEOUT = 30.0

# ---------------------------------------------------------------------------
# Symptom scenarios — varied descriptions that span different HPO domains
# ---------------------------------------------------------------------------
SYMPTOM_SCENARIOS: list[dict[str, Any]] = [
    {
        "description": "I've had a really bad headache all morning, throbbing on the left side, about a 7 out of 10. It started around 6am and I also felt nauseous.",
        "followup": "No, no fever. Just the headache and nausea. Nothing else.",
    },
    {
        "description": "Extreme fatigue today. I could barely get out of bed. Muscle weakness in my legs, severity around 8. It's been like this since yesterday evening.",
        "followup": "No pain, just weakness and tiredness. I slept 10 hours but still feel exhausted.",
    },
    {
        "description": "Joint pain in both knees and ankles, stiffness that's worse in the morning. About a 6 out of 10. Lasted roughly 3 hours this morning.",
        "followup": "Yes, the stiffness improved a bit after moving around. No swelling I could see.",
    },
    {
        "description": "Abdominal cramping and bloating after eating, severity 5. Also had diarrhea twice this afternoon. Started about 2 hours after lunch.",
        "followup": "I didn't eat anything unusual. No blood, just loose stools and cramping.",
    },
    {
        "description": "Heart palpitations for about 20 minutes this morning, felt like my heart was racing. Severity 6. I was just sitting at my desk.",
        "followup": "No chest pain or shortness of breath. Just the racing feeling. It went away on its own.",
    },
    {
        "description": "Severe brain fog today — I can't concentrate on anything, forgot words mid-sentence three times. Cognitive difficulty around 7 out of 10.",
        "followup": "No headache with it. Just the confusion and memory issues. It's been happening more often lately.",
    },
    {
        "description": "Skin rash on my forearms and neck, itchy and red, about a 5 in severity. Appeared this morning, no idea what triggered it.",
        "followup": "I haven't changed any soaps or detergents. No new foods either. The rash is flat, not raised.",
    },
    {
        "description": "Blurry vision in my right eye for a few hours this afternoon, severity 6. I also had light sensitivity. No pain.",
        "followup": "My vision is back to normal now. This happened once last month too.",
    },
    {
        "description": "I had a tremor in my right hand this morning while trying to eat breakfast. Severity 5. It lasted about 30 minutes.",
        "followup": "It's happened a few times this week. No pain associated with the tremor.",
    },
    {
        "description": "Difficulty swallowing today, food felt like it was getting stuck. Severity 4. Also some mild chest discomfort after eating.",
        "followup": "Liquids are fine, only happens with solid food. No heartburn, just the swallowing issue.",
    },
    {
        "description": "Very low mood and extreme fatigue, couldn't leave the house. Severity 7. Also had a mild headache in the evening.",
        "followup": "I slept poorly last night, maybe 4 hours. The mood has been low for a few days.",
    },
    {
        "description": "Shortness of breath climbing one flight of stairs, had to stop and rest. Severity 6. No cough or chest pain.",
        "followup": "I'm not usually short of breath like this. It's been happening for about a week.",
    },
    {
        "description": "Temperature sensitivity today — felt cold when it was warm outside, hands were ice cold. Severity 4. Also tired.",
        "followup": "No fever measured. Just feeling cold even indoors with heating on.",
    },
    {
        "description": "Woke up with severe lower back pain radiating down my left leg, severity 8. Hard to stand up straight.",
        "followup": "I didn't do any heavy lifting. The pain is worse when sitting. Ibuprofen helped a little.",
    },
    {
        "description": "Excessive thirst and frequent urination today — went to the bathroom 8 times. Severity 5. No pain when urinating.",
        "followup": "I didn't drink more than usual. This has happened a few times this month.",
    },
    {
        "description": "Sudden dizziness and vertigo when I stood up, felt like the room was spinning. Severity 7. Lasted about 10 minutes.",
        "followup": "No nausea with it this time. I had to sit down immediately. Happened twice today.",
    },
    {
        "description": "Painful muscle cramps in my calves and feet overnight, woke me up twice. Severity 6. My feet also felt numb.",
        "followup": "Stretching helped a bit. The numbness in my feet is new, hadn't noticed it before.",
    },
    {
        "description": "Unusually heavy hair loss in the shower today, noticeable clumps. Severity 4. My scalp has also been itchy.",
        "followup": "I haven't changed shampoos. This has been gradually getting worse over two months.",
    },
    {
        "description": "Night sweats soaked my sheets, woke up at 3am completely drenched. Severity 7. No fever, felt cold afterward.",
        "followup": "This is the third time this week. No other symptoms overnight.",
    },
    {
        "description": "Tingling and pins and needles in both hands and feet throughout the day. Severity 5. Worse when sitting still.",
        "followup": "The tingling is symmetrical — both sides equally. No pain with it.",
    },
    {
        "description": "Swollen lymph nodes in my neck, noticed them while showering. Tender to touch, severity 4. Mildly sore throat.",
        "followup": "No fever. The nodes have been there about 4 days. No other infections that I know of.",
    },
    {
        "description": "Chest tightness and difficulty taking a deep breath, severity 6. It comes and goes, worse when lying down.",
        "followup": "No cough or wheezing. It's not painful, more like pressure. Happens mostly at night.",
    },
    {
        "description": "Photosensitivity today, even indoor lighting felt painful. Had to wear sunglasses inside. Severity 7 for the eye pain.",
        "followup": "I also had a mild headache with it. This happens about once a week.",
    },
    {
        "description": "Sudden unexplained weight loss — lost 4 pounds in two weeks without trying. No changes to diet or exercise.",
        "followup": "No appetite changes really, I'm eating normally. No diarrhea or vomiting.",
    },
    {
        "description": "Oral ulcers, two painful sores inside my cheek. Severity 5. Hard to eat comfortably.",
        "followup": "I get these regularly, maybe once a month. They usually take a week to heal.",
    },
    {
        "description": "Raynaud's-like episode — my fingers turned white then blue in a cold room. Took 20 minutes to warm up. Severity 5.",
        "followup": "This happens whenever I'm in air conditioning. My toes do it too sometimes.",
    },
    {
        "description": "Severe fatigue after minimal exertion — walked to the mailbox and needed to rest for an hour. Severity 9.",
        "followup": "This post-exertional malaise has been a pattern for months. Rest doesn't fully restore my energy.",
    },
    {
        "description": "Dry eyes and dry mouth all day, severity 4. My eyes felt gritty and I had trouble swallowing without water.",
        "followup": "I drink plenty of water. The dryness is worse in the morning.",
    },
    {
        "description": "Sharp stabbing pain in my lower left abdomen, intermittent, severity 7. Lasted most of the afternoon.",
        "followup": "No nausea or fever. The pain came in waves. I'm not sure if it's related to eating.",
    },
    {
        "description": "Significant swelling in both ankles by end of day, pitting edema, severity 5. My shoes were tight.",
        "followup": "Swelling is worse after standing. It goes down overnight when I elevate my feet.",
    },
    {
        "description": "Confusion and disorientation episode this morning, couldn't remember where I was briefly. Severity 8. Very frightening.",
        "followup": "It lasted about 5 minutes then cleared. I had slept well. No headache before or after.",
    },
    {
        "description": "Persistent ringing in both ears (tinnitus) all day, severity 5. Harder to concentrate because of the noise.",
        "followup": "It's louder than usual today. I've had mild tinnitus for years but today was worse.",
    },
    {
        "description": "Urticarial hives appeared on my torso and arms, intensely itchy, severity 6. Appeared within an hour.",
        "followup": "I took antihistamine, helped slightly. No throat swelling or breathing difficulty.",
    },
    {
        "description": "Severe insomnia last night, couldn't sleep at all despite being exhausted. Severity 7. Mind was racing.",
        "followup": "No specific worries keeping me up. This happens a few times a month.",
    },
    {
        "description": "New onset of widespread body pain, feels like a bad flu but without fever. Severity 7. Every muscle hurts.",
        "followup": "No fever, normal temperature. Started two days ago. Rest doesn't help much.",
    },
]


def _extract_quick_log(description: str) -> list[dict]:
    """
    Extract a QuickLogEntry from a scenario description.
    Parses severity and a short symptom name so the AI receives pre-structured
    data in addition to the free-text message — matches StartCheckInRequest.quick_log_entries.
    """
    # Extract severity: "severity 7", "7 out of 10", "about a 7", "around 8"
    sev_match = re.search(
        r'\b(\d+)\s*(?:out\s+of\s*10|\/10)|severity\s*(?:around\s*)?(\d+)|about\s+a?\s*(\d+)',
        description, re.IGNORECASE,
    )
    severity = 5  # default
    if sev_match:
        raw = next(v for v in sev_match.groups() if v is not None)
        severity = max(1, min(10, int(raw)))

    # Symptom name: first clause, stripped of common filler phrases
    first_clause = description.split(',')[0].split('.')[0]
    symptom_name = re.sub(
        r'^(i[\'\u2019]?ve\s+had|i\s+had|i\s+have|i\s+got|my)\s+',
        '', first_clause, flags=re.IGNORECASE,
    ).strip()
    # Remove trailing time qualifiers
    symptom_name = re.sub(
        r'\s+(all\s+morning|today|this\s+morning|this\s+afternoon|overnight|since|for).*$',
        '', symptom_name, flags=re.IGNORECASE,
    ).strip().lower()
    symptom_name = symptom_name[:40] or "symptom"

    return [{"symptom_name": symptom_name, "severity": severity}]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def post(client: httpx.Client, path: str, body: dict) -> dict:
    resp = client.post(path, json=body)
    resp.raise_for_status()
    return resp.json()


def run_check_in_session(
    client: httpx.Client,
    patient_id: str,
    scenario: dict[str, Any],
    session_num: int,
) -> bool:
    """
    Drive one full check-in session to completion.
    Returns True on success, False on failure.
    """
    try:
        # 1. Start — pass pre-structured quick_log_entries alongside free text
        quick_log = _extract_quick_log(scenario["description"])
        start_resp = post(client, "/check-in/start", {
            "patient_id": patient_id,
            "quick_log_entries": quick_log,
        })
        session_id = start_resp["session_id"]
        status = start_resp["status"]
        print(f"  [{session_num}] session={session_id[:8]}… status={status}")

        # 2. Send symptom description
        turn = 0
        patient_messages = [scenario["description"], scenario["followup"], "No other symptoms today."]

        while status not in ("awaiting_confirmation", "saved", "filed") and turn < MAX_TURNS_PER_SESSION:
            msg = patient_messages[min(turn, len(patient_messages) - 1)]
            msg_resp = post(client, "/check-in/message", {
                "session_id": session_id,
                "patient_message": msg,
            })
            status = msg_resp["status"]
            turn += 1
            print(f"  [{session_num}] turn={turn} status={status}")

        # 3. Confirm
        if status == "awaiting_confirmation":
            confirm_resp = post(client, "/check-in/confirm", {
                "session_id": session_id,
                "decision": "confirm",
            })
            status = confirm_resp["status"]
            obs_ids = confirm_resp.get("fhir_observation_ids", [])
            print(f"  [{session_num}] confirmed  status={status}  observations={len(obs_ids)}")
            return True
        else:
            print(f"  [{session_num}] WARNING: ended with status={status} (not confirmed)")
            return False

    except httpx.HTTPStatusError as exc:
        print(f"  [{session_num}] HTTP error {exc.response.status_code}: {exc.response.text[:200]}")
        return False
    except Exception as exc:
        print(f"  [{session_num}] error: {exc}")
        return False


def run_hypothesis(client: httpx.Client, patient_id: str) -> None:
    """Trigger hypothesis analysis and print the result."""
    print("\n--- Triggering hypothesis analysis ---")
    try:
        resp = post(client, "/hypothesis/start", {"patient_id": patient_id})
        session_id = resp["session_id"]
        status = resp["status"]
        obs = resp.get("observations_available", "?")
        print(f"  hypothesis session={session_id[:8]}… status={status} observations={obs}")

        if status == "awaiting_review":
            report_resp = client.get(f"/hypothesis/{session_id}/report")
            report_resp.raise_for_status()
            report = report_resp.json()
            profiles = report.get("profiles", [])
            print(f"  {len(profiles)} hypothesis profile(s) generated:")
            for p in profiles[:3]:
                print(f"    • {p.get('disease_name', '?')} (confidence={p.get('confidence_score', '?')})")
            if len(profiles) > 3:
                print(f"    … and {len(profiles) - 3} more")

    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:300]
        print(f"  hypothesis error {exc.response.status_code}: {body}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Seed symptom check-ins into Sukshma-Jignaasa")
    parser.add_argument("--count", type=int, default=5, help="Number of check-in sessions to create (default: 5)")
    parser.add_argument("--patient-id", default=DEFAULT_PATIENT_ID, help=f"Patient ID (default: {DEFAULT_PATIENT_ID})")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"Backend base URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--hypothesis", action="store_true", help="Run hypothesis analysis after seeding")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds to wait between sessions (default: 0.5)")
    args = parser.parse_args()

    print(f"Seeding {args.count} check-in session(s) for patient '{args.patient_id}'")
    print(f"Backend: {args.base_url}")
    print()

    # Cycle through scenarios, repeating if count > len(SYMPTOM_SCENARIOS)
    scenarios = [SYMPTOM_SCENARIOS[i % len(SYMPTOM_SCENARIOS)] for i in range(args.count)]
    random.shuffle(scenarios)

    success = 0
    failed = 0

    with httpx.Client(base_url=args.base_url, timeout=REQUEST_TIMEOUT) as client:
        # Quick connectivity check
        try:
            health = client.get("/health")
            health.raise_for_status()
        except Exception as exc:
            print(f"ERROR: Cannot reach backend at {args.base_url} — {exc}")
            print("Make sure the backend is running: cd backend && uvicorn main:app --reload")
            sys.exit(1)

        for i, scenario in enumerate(scenarios, start=1):
            ok = run_check_in_session(client, args.patient_id, scenario, i)
            if ok:
                success += 1
            else:
                failed += 1
            if i < len(scenarios):
                time.sleep(args.delay)

        print(f"\nDone: {success} succeeded, {failed} failed out of {args.count} sessions.")

        if args.hypothesis:
            run_hypothesis(client, args.patient_id)
        elif success >= 30:
            print(f"\nTip: You now have enough observations for hypothesis analysis.")
            print(f"Run with --hypothesis to trigger it, or POST /hypothesis/start from the UI.")


if __name__ == "__main__":
    main()
