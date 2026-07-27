"""
HPO Validator
-------------
Validates HPO IDs against the curated vocabulary before any FHIR write.
Strips or rejects IDs that don't exist in hpo_terms.json.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_HPO_VOCAB_PATH = Path(__file__).resolve().parents[2] / "app" / "data" / "hpo_terms.json"

# Loaded once at module import
def _load() -> dict[str, dict]:
    with _HPO_VOCAB_PATH.open("r", encoding="utf-8") as f:
        terms = json.load(f)
    # Deduplicate by hpo_id — keep last entry for duplicates
    return {t["hpo_id"]: t for t in terms}


_VOCAB: dict[str, dict] = _load()


def is_valid(hpo_id: str) -> bool:
    """Return True if the HPO ID exists in the curated vocabulary."""
    return hpo_id in _VOCAB


def get_label(hpo_id: str) -> str | None:
    """Return the canonical label for an HPO ID, or None if not in vocabulary."""
    entry = _VOCAB.get(hpo_id)
    return entry["label"] if entry else None


def strip_invalid(hpo_terms: list[dict]) -> list[dict]:
    """
    Remove HPO term entries whose hpo_id is not in the curated vocabulary.
    Logs a warning for each stripped term.
    """
    valid = []
    for term in hpo_terms:
        hpo_id = term.get("hpo_id", "")
        if is_valid(hpo_id):
            valid.append(term)
        else:
            logger.warning(
                "Stripping hallucinated HPO ID '%s' (label: '%s') — not in vocabulary",
                hpo_id,
                term.get("label", ""),
            )
    return valid


def validate_all(hpo_terms: list[dict]) -> tuple[list[dict], list[str]]:
    """
    Validate a list of HPO term dicts.
    Returns (valid_terms, list_of_invalid_ids).
    """
    valid, invalid_ids = [], []
    for term in hpo_terms:
        hpo_id = term.get("hpo_id", "")
        if is_valid(hpo_id):
            valid.append(term)
        else:
            invalid_ids.append(hpo_id)
    return valid, invalid_ids
