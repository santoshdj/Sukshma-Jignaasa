"""
fetch_patient_fhir.py — Retrieve and display a patient's FHIR resources from Medblocks.

Fetches:
  - Patient resource
  - Observations (all, or filtered by date range)

Usage:
    cd backend
    python scripts/fetch_patient_fhir.py
    python scripts/fetch_patient_fhir.py --patient-id patient-demo-001
    python scripts/fetch_patient_fhir.py --patient-id patient-demo-001 --since 2026-01-01
    python scripts/fetch_patient_fhir.py --patient-id patient-demo-001 --resource Observation --count 5
    python scripts/fetch_patient_fhir.py --patient-id patient-demo-001 --raw
"""

from __future__ import annotations

import argparse
import json
import sys
import pathlib
import os
from datetime import datetime, timezone

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
os.chdir(pathlib.Path(__file__).parent.parent)  # so .env is found

from app.utils.config import get_settings

SEP = "─" * 64


# ── Helpers ───────────────────────────────────────────────────────────────────

def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/fhir+json",
        "Content-Type": "application/fhir+json",
    }


def _print_sep(title: str = "") -> None:
    if title:
        pad = max(0, (len(SEP) - len(title) - 2) // 2)
        print(f"\n{'─' * pad} {title} {'─' * pad}")
    else:
        print(f"\n{SEP}")


def _ok(msg: str) -> None:
    print(f"  ✓  {msg}")


def _warn(msg: str) -> None:
    print(f"  ⚠  {msg}")


def _err(msg: str) -> None:
    print(f"  ✗  {msg}", file=sys.stderr)


# ── Fetchers ──────────────────────────────────────────────────────────────────

def fetch_patient(
    client: httpx.Client,
    fhir_base: str,
    token: str,
    patient_id: str,
    raw: bool,
) -> bool:
    """GET /Patient/{id}"""
    _print_sep(f"Patient  {patient_id}")
    url = f"{fhir_base}/Patient/{patient_id}"
    try:
        resp = client.get(url, headers=_auth_headers(token), timeout=15)
        print(f"  URL    : {url}")
        print(f"  Status : {resp.status_code}")

        if resp.status_code == 404:
            _warn("Patient not found — check patient ID or create the Patient resource first")
            return False

        resp.raise_for_status()
        data = resp.json()

        if raw:
            print(json.dumps(data, indent=2))
            return True

        name_parts = data.get("name", [{}])[0]
        given = " ".join(name_parts.get("given", []))
        family = name_parts.get("family", "")
        dob = data.get("birthDate", "unknown")
        gender = data.get("gender", "unknown")
        _ok(f"Name   : {given} {family}".strip() or "(no name)")
        _ok(f"DOB    : {dob}")
        _ok(f"Gender : {gender}")
        _ok(f"ID     : {data.get('id', patient_id)}")
        return True

    except httpx.HTTPStatusError as exc:
        _err(f"HTTP {exc.response.status_code}: {exc.response.text[:300]}")
        return False
    except httpx.ConnectError as exc:
        _err(f"Connection error — is the FHIR base URL correct? ({exc})")
        return False
    except Exception as exc:
        _err(f"Unexpected error: {type(exc).__name__}: {exc}")
        return False


def _extract_resources(bundle: dict) -> list[dict]:
    """
    Flatten all Observation resources out of a FHIR Bundle.
    Handles both standard (entry[].resource) and bare-resource (entry[] IS the resource) formats.
    Also handles nested Bundles (one level deep).
    """
    resources: list[dict] = []
    for entry in bundle.get("entry", []):
        # Standard FHIR: entry has a "resource" key
        resource = entry.get("resource") or entry
        rt = resource.get("resourceType", "")
        if rt == "Observation":
            resources.append(resource)
        elif rt == "Bundle":
            # Nested bundle — flatten one level
            for inner_entry in resource.get("entry", []):
                inner = inner_entry.get("resource") or inner_entry
                if inner.get("resourceType") == "Observation":
                    resources.append(inner)
    return resources


def fetch_observations(
    client: httpx.Client,
    fhir_base: str,
    token: str,
    patient_id: str,
    since: str | None,
    count: int,
    raw: bool,
) -> None:
    """GET /Observation — tries multiple subject parameter formats used by different FHIR servers."""
    _print_sep("Observations")

    base_params: dict[str, str | int] = {"_sort": "-date", "_count": count}
    if since:
        base_params["date"] = f"ge{since}"

    # Different FHIR servers accept different subject search parameter formats.
    # Try them in order and use the first one that returns results.
    subject_variants = [
        {"subject": f"Patient/{patient_id}"},   # standard relative reference
        {"subject": patient_id},                 # bare ID (some servers)
        {"patient": patient_id},                 # 'patient' shorthand (some servers)
        {"patient": f"Patient/{patient_id}"},    # 'patient' with type prefix
    ]

    url = f"{fhir_base}/Observation"
    found_variant: dict | None = None
    bundle: dict = {}

    for variant in subject_variants:
        params = {**base_params, **variant}
        print(f"  Trying : {url}  params={params}")
        try:
            resp = client.get(url, headers=_auth_headers(token), params=params, timeout=15)
            print(f"  Status : {resp.status_code}")
            if resp.status_code != 200:
                _warn(f"  Non-200 ({resp.status_code}) for params {variant}, skipping")
                continue
            candidate = resp.json()
            total = candidate.get("total", 0)
            entry_count = len(candidate.get("entry", []))
            print(f"  Total={total}  Entries={entry_count}")
            if total or entry_count:
                bundle = candidate
                found_variant = variant
                _ok(f"Results found with params: {variant}")
                break
        except Exception as exc:
            _err(f"  Error with {variant}: {exc}")

    # If all subject variants returned 0, this server doesn't index the subject
    # search parameter. Fall back to fetching all observations and filtering client-side.
    if not found_variant:
        _warn(
            "Server does not support subject filtering — fetching all observations "
            f"and filtering client-side for Patient/{patient_id}."
        )
        all_observations: list[dict] = []
        next_url: str | None = url
        next_params: dict = {**base_params, "_count": 50}
        page = 0
        target_ref = f"Patient/{patient_id}"

        while next_url and page < 20:  # safety cap: max 1000 observations
            page += 1
            try:
                resp = client.get(next_url, headers=_auth_headers(token), params=next_params if page == 1 else {}, timeout=15)
                if resp.status_code != 200:
                    _err(f"Unfiltered fetch page {page} returned {resp.status_code}")
                    break
                page_bundle = resp.json()
                page_resources = _extract_resources(page_bundle)
                matched = [
                    o for o in page_resources
                    if o.get("subject", {}).get("reference", "") == target_ref
                ]
                all_observations.extend(matched)
                print(f"  Page {page}: {len(page_resources)} obs fetched, {len(matched)} matched patient")

                # Follow pagination links
                links = {lnk["relation"]: lnk["url"] for lnk in page_bundle.get("link", [])}
                next_url = links.get("next")
                # Stop once we have enough for the requested count
                if len(all_observations) >= count:
                    all_observations = all_observations[:count]
                    break
            except Exception as exc:
                _err(f"Unfiltered fetch error page {page}: {exc}")
                break

        if not all_observations:
            _warn(
                f"No Observations found for Patient/{patient_id} after full workspace scan. "
                "Complete a check-in or run: python scripts/seed_check_ins.py"
            )
            return

        _ok(f"Found {len(all_observations)} observation(s) for Patient/{patient_id} (client-side filtered)")
        bundle = {"entry": [{"resource": o} for o in all_observations]}

    observations = _extract_resources(bundle)
    print(f"\n  Bundle entry count  : {len(bundle.get('entry', []))}")
    print(f"  Observations found  : {len(observations)}")

    if raw:
        print()
        for i, obs in enumerate(observations, 1):
            print(f"── Observation {i}/{len(observations)} ──────────────────────────")
            print(json.dumps(obs, indent=2))
        if not observations:
            _warn("No Observation resources in bundle — printing raw bundle instead")
            print(json.dumps(bundle, indent=2))
        return

    if not observations:
        _warn("No observations found after extraction.")
        return

    print()
    for i, obs in enumerate(observations, 1):
        obs_id = obs.get("id", "—")
        effective = obs.get("effectiveDateTime", "—")
        code_text = obs.get("code", {}).get("text", "—")
        status = obs.get("status", "—")
        components = obs.get("component", [])

        # Extract key components for summary
        comp_map = {
            c["code"]["text"]: (
                c.get("valueInteger")
                or c.get("valueString")
                or c.get("valueBoolean")
            )
            for c in components
            if "text" in c.get("code", {})
        }
        severity = comp_map.get("severity", "—")
        body_sys = comp_map.get("body_system", "—")
        trigger = comp_map.get("probable_trigger", "")
        no_symptom = comp_map.get("is_no_symptom_day", False)

        print(f"  [{i:>3}] id={obs_id}")
        print(f"        date      : {effective}")
        print(f"        status    : {status}")
        if no_symptom:
            print(f"        type      : no-symptom baseline day")
        else:
            print(f"        symptom   : {code_text}")
            print(f"        severity  : {severity}/10")
            print(f"        system    : {body_sys}")
            if trigger:
                print(f"        trigger   : {trigger}")
        print()

    # Pagination hint
    links = {lnk["relation"]: lnk["url"] for lnk in bundle.get("link", [])}
    if "next" in links:
        _warn(f"More results available — increase --count (next page: {links['next']})")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch patient FHIR resources from Medblocks")
    parser.add_argument("--patient-id", default="patient-demo-001", help="FHIR Patient ID")
    parser.add_argument(
        "--resource",
        choices=["all", "Patient", "Observation"],
        default="all",
        help="Which resource type to fetch (default: all)",
    )
    parser.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        default=None,
        help="Only return Observations on or after this date",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=20,
        help="Max Observations to return (default: 20)",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print raw FHIR JSON instead of formatted summary",
    )
    args = parser.parse_args()

    settings = get_settings()
    fhir_base = (settings.medblocks_fhir_base_url or "https://fhir.medblocks.com/fhir/R4").rstrip("/")
    token = settings.medblocks_fhir_bearer_token

    print(f"\nFHIR base : {fhir_base}")
    print(f"Patient   : {args.patient_id}")
    print(f"Auth      : {'Bearer ***' + token[-4:] if token else 'NONE — will likely get 401'}")
    if args.since:
        print(f"Since     : {args.since}")

    if not token:
        _warn("MEDBLOCKS_FHIR_BEARER_TOKEN is not set — requests will be unauthenticated")

    with httpx.Client() as client:
        if args.resource in ("all", "Patient"):
            fetch_patient(client, fhir_base, token, args.patient_id, args.raw)

        if args.resource in ("all", "Observation"):
            fetch_observations(
                client, fhir_base, token, args.patient_id,
                since=args.since, count=args.count, raw=args.raw,
            )

    _print_sep()
    print("Done.\n")


if __name__ == "__main__":
    main()
