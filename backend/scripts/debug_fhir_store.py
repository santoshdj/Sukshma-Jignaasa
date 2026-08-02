"""
debug_fhir_store.py — Diagnose Medblocks FHIR store connectivity and data presence.

Runs four checks and prints results:
  1. FHIR server reachability (GET /metadata)
  2. Auth check (GET /Observation with API key — expect 200 not 401)
  3. Observation count for the patient (mirrors what hypothesis_node does)
  4. Raw write test — POST one minimal Observation, verify it comes back

Usage:
    cd backend
    python scripts/debug_fhir_store.py
    python scripts/debug_fhir_store.py --patient-id patient-demo-001
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta

import httpx

# Load settings the same way the app does
import os, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
os.chdir(pathlib.Path(__file__).parent.parent)  # so .env is found

from app.utils.config import get_settings

SEP = "-" * 60


def _headers_with_auth(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/fhir+json",
        "Content-Type": "application/fhir+json",
    }


def _headers_no_auth() -> dict:
    return {
        "Accept": "application/fhir+json",
        "Content-Type": "application/fhir+json",
    }


def check_1_metadata(client: httpx.Client, fhir_base: str) -> bool:
    """GET /metadata — checks the FHIR server is alive at all."""
    print(f"\n{SEP}")
    print("CHECK 1: FHIR server reachability (GET /metadata)")
    url = f"{fhir_base}/metadata"
    try:
        resp = client.get(url, headers={"Accept": "application/fhir+json"}, timeout=10)
        print(f"  URL    : {url}")
        print(f"  Status : {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"  FHIR   : {data.get('fhirVersion', '?')}  software={data.get('software', {}).get('name', '?')}")
            print("  RESULT : ✓ FHIR server is reachable")
            return True
        else:
            print(f"  Body   : {resp.text[:300]}")
            print("  RESULT : ✗ FHIR server returned non-200")
            return False
    except Exception as exc:
        print(f"  ERROR  : {exc}")
        print("  RESULT : ✗ Cannot reach FHIR server")
        return False


def check_2_auth(client: httpx.Client, fhir_base: str, api_key: str) -> bool:
    """GET /Observation?_count=1 — checks auth is accepted."""
    print(f"\n{SEP}")
    print("CHECK 2: Auth check (GET /Observation?_count=1 with Bearer token)")
    key_preview = f"{api_key[:8]}…{api_key[-4:]}" if len(api_key) > 12 else repr(api_key)
    print(f"  Key    : {key_preview}")
    url = f"{fhir_base}/Observation"
    try:
        resp = client.get(
            url,
            headers=_headers_with_auth(api_key),
            params={"_count": "1"},
            timeout=15,
        )
        print(f"  URL    : {url}")
        print(f"  Status : {resp.status_code}")
        if resp.status_code == 200:
            print("  RESULT : ✓ Auth accepted — API key is valid for FHIR server")
            return True
        elif resp.status_code == 401:
            print(f"  Body   : {resp.text[:300]}")
            print("  RESULT : ✗ 401 — API key rejected by FHIR server")
            return False
        elif resp.status_code == 403:
            print(f"  Body   : {resp.text[:300]}")
            print("  RESULT : ✗ 403 — authenticated but no permission to read Observations")
            return False
        else:
            print(f"  Body   : {resp.text[:300]}")
            print(f"  RESULT : ? Unexpected status {resp.status_code}")
            return False
    except Exception as exc:
        print(f"  ERROR  : {exc}")
        return False


def check_2b_no_auth(client: httpx.Client, fhir_base: str) -> None:
    """GET /Observation without auth — check if server is open."""
    print(f"\n  --- Bonus: same request WITHOUT Authorization header ---")
    url = f"{fhir_base}/Observation"
    try:
        resp = client.get(url, headers=_headers_no_auth(), params={"_count": "1"}, timeout=15)
        print(f"  Status without auth: {resp.status_code}")
        if resp.status_code == 200:
            print("  NOTE: Server accepts unauthenticated reads — auth header may be optional")
        else:
            print(f"  Body : {resp.text[:200]}")
    except Exception as exc:
        print(f"  ERROR: {exc}")


def check_3_patient_observations(
    client: httpx.Client,
    fhir_base: str,
    api_key: str,
    patient_id: str,
) -> int:
    """Exact query used by hypothesis_node — returns observation count."""
    print(f"\n{SEP}")
    print(f"CHECK 3: Patient observations (mirrors hypothesis_node query)")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    params = {
        "subject": f"Patient/{patient_id}",
        "date": f"ge{cutoff}",
        "_count": "200",
    }
    print(f"  Patient: {patient_id}")
    print(f"  Cutoff : {cutoff} (90 days ago)")
    print(f"  Params : {params}")
    url = f"{fhir_base}/Observation"
    try:
        resp = client.get(url, headers=_headers_with_auth(api_key), params=params, timeout=20)
        print(f"  Status : {resp.status_code}")
        if resp.status_code == 200:
            bundle = resp.json()
            total = bundle.get("total", "?")
            entries = bundle.get("entry", [])
            obs_count = sum(
                1 for e in entries
                if e.get("resource", {}).get("resourceType") == "Observation"
            )
            print(f"  Bundle total (server-reported): {total}")
            print(f"  Observations in this page     : {obs_count}")
            if obs_count > 0:
                print(f"  RESULT : ✓ Data found — hypothesis should have {obs_count} observations")
                # Show sample
                sample = entries[0].get("resource", {}) if entries else {}
                print(f"  Sample : id={sample.get('id','?')}  status={sample.get('status','?')}  subject={sample.get('subject',{})}")
            else:
                print("  RESULT : ✗ No observations found for this patient in last 90 days")
                print("  Check  : Are observations written with the correct patient_id reference?")
                # Try without patient filter
                _check_all_observations(client, fhir_base, api_key)
            return obs_count
        else:
            print(f"  Body   : {resp.text[:300]}")
            print(f"  RESULT : ✗ Query failed with status {resp.status_code}")
            return 0
    except Exception as exc:
        print(f"  ERROR  : {exc}")
        return 0


def _check_all_observations(client: httpx.Client, fhir_base: str, api_key: str) -> None:
    """Helper: fetch all observations (no patient filter) to see what's actually there."""
    print(f"\n  --- Checking ALL observations (no patient filter) ---")
    try:
        resp = client.get(
            f"{fhir_base}/Observation",
            headers=_headers_with_auth(api_key),
            params={"_count": "5", "_sort": "-date"},
            timeout=20,
        )
        if resp.status_code == 200:
            bundle = resp.json()
            entries = bundle.get("entry", [])
            total = bundle.get("total", "?")
            print(f"  Total observations in store: {total}")
            if entries:
                print("  Most recent 5:")
                for e in entries[:5]:
                    r = e.get("resource", {})
                    subj = r.get("subject", {}).get("reference", "?")
                    print(f"    id={r.get('id','?')}  subject={subj}  status={r.get('status','?')}")
            else:
                print("  Store appears empty — no observations written at all")
        else:
            print(f"  Status: {resp.status_code}  Body: {resp.text[:200]}")
    except Exception as exc:
        print(f"  ERROR: {exc}")


def check_4_write_test(
    client: httpx.Client,
    fhir_base: str,
    api_key: str,
    patient_id: str,
) -> bool:
    """POST a minimal Observation, then verify it was stored."""
    print(f"\n{SEP}")
    print("CHECK 4: Write test — POST one minimal Observation")
    now = datetime.now(timezone.utc).isoformat()
    obs = {
        "resourceType": "Observation",
        "status": "final",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "survey"}]}],
        "code": {"text": "debug-test-observation"},
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": now,
        "valueString": "debug-write-test",
    }
    url = f"{fhir_base}/Observation"
    try:
        # Try WITH auth
        resp = client.post(url, headers=_headers_with_auth(api_key), json=obs, timeout=15)
        print(f"  POST with auth   → status {resp.status_code}")
        if resp.status_code in (200, 201):
            created = resp.json()
            obs_id = created.get("id", "?")
            print(f"  Created id       : {obs_id}")
            print("  RESULT : ✓ Write succeeded with auth")
            # Verify it can be read back
            read_resp = client.get(
                f"{url}/{obs_id}",
                headers=_headers_with_auth(api_key),
                timeout=10,
            )
            print(f"  Read-back status : {read_resp.status_code}")
            if read_resp.status_code == 200:
                print("  RESULT : ✓ Observation confirmed in store")
            else:
                print(f"  Read-back body   : {read_resp.text[:200]}")
            return True
        else:
            print(f"  Body             : {resp.text[:300]}")
            # Try WITHOUT auth
            resp2 = client.post(url, headers=_headers_no_auth(), json=obs, timeout=15)
            print(f"  POST without auth→ status {resp2.status_code}")
            if resp2.status_code in (200, 201):
                print("  NOTE: Write succeeded WITHOUT auth header")
                print("  This means fhir_writer.py (which sends no auth) CAN write — check read auth instead")
                return True
            else:
                print(f"  Body (no auth)   : {resp2.text[:200]}")
                print("  RESULT : ✗ Write failed both with and without auth")
                return False
    except Exception as exc:
        print(f"  ERROR  : {exc}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug Medblocks FHIR store")
    parser.add_argument("--patient-id", default="patient-demo-001")
    args = parser.parse_args()

    settings = get_settings()
    api_key = settings.medblocks_api_key
    fhir_token = settings.medblocks_fhir_bearer_token
    fhir_base = settings.medblocks_fhir_base_url.rstrip("/")

    print("=" * 60)
    print("Medblocks FHIR Store Diagnostic")
    print("=" * 60)
    print(f"FHIR base  : {fhir_base}")
    print(f"Patient    : {args.patient_id}")
    api_preview = f"{api_key[:8]}\u2026{api_key[-4:]}" if len(api_key) > 12 else ("<empty>" if not api_key else "<short>")
    print(f"API key    : {api_preview}")
    fhir_preview = f"{fhir_token[:8]}\u2026{fhir_token[-4:]}" if len(fhir_token) > 12 else ("<empty>" if not fhir_token else "<short>")
    print(f"FHIR token : {fhir_preview}")

    results: dict[str, bool | int] = {}

    with httpx.Client(timeout=20.0) as client:
        results["metadata"] = check_1_metadata(client, fhir_base)
        results["auth"] = check_2_auth(client, fhir_base, fhir_token)
        check_2b_no_auth(client, fhir_base)
        results["obs_count"] = check_3_patient_observations(client, fhir_base, fhir_token, args.patient_id)
        results["write"] = check_4_write_test(client, fhir_base, fhir_token, args.patient_id)

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    print(f"  FHIR reachable : {'✓' if results['metadata'] else '✗'}")
    print(f"  Auth valid     : {'✓' if results['auth'] else '✗'}")
    print(f"  Observations   : {results['obs_count']} (need ≥30 for hypothesis)")
    print(f"  Write test     : {'✓' if results['write'] else '✗'}")

    obs = results["obs_count"]
    if not results["metadata"]:
        print("\nACTION: FHIR server unreachable — check MEDBLOCKS_FHIR_BASE_URL in .env")
    elif not results["auth"]:
        print("\nACTION: Auth rejected — API key invalid for FHIR server")
        print("        Get a new key from https://app.medblocks.com/settings/api-keys")
    elif obs == 0 and results["write"]:
        print("\nACTION: Auth works and writes succeed, but no observations found for this patient.")
        print("        Most likely cause: fhir_writer.py sends no Authorization header (bug fixed")
        print("        in check_in.py — make sure the fix was applied and restart the backend,")
        print("        then re-run the seed script.")
    elif isinstance(obs, int) and obs < 30:
        print(f"\nACTION: Only {obs} observations — run seed script with --count 35")
    elif isinstance(obs, int) and obs >= 30:
        print("\n✓ All checks passed — hypothesis analysis should work.")


if __name__ == "__main__":
    main()
