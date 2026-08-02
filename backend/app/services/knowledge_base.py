"""
Knowledge Base — ChromaDB vector store for rare disease profiles.

Build: reads rare_disease_profiles.json, embeds each profile document,
       persists to data/chroma_db/.

Search: builds a query string from the patient's symptom fingerprint,
        retrieves top-K matching profiles.

Uses chromadb's default embedding function (ONNX all-MiniLM-L6-v2).
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

from app.models.hypothesis import RareDiseaseProfile

logger = logging.getLogger(__name__)

_PROFILES_PATH = Path(__file__).resolve().parents[2] / "app" / "data" / "rare_disease_profiles.json"
_CHROMA_PATH = Path(__file__).resolve().parents[2] / "data" / "chroma_db"
_COLLECTION_NAME = "rare_disease_profiles"


def _load_profiles() -> list[RareDiseaseProfile]:
    with _PROFILES_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return [RareDiseaseProfile(**item) for item in data]


def _profile_to_document(profile: RareDiseaseProfile) -> str:
    """Build a single rich text string for embedding."""
    hpo_all = profile.cardinal_hpo_terms + profile.supportive_hpo_terms
    return (
        f"{profile.name}. "
        f"{profile.description} "
        f"Key HPO terms: {', '.join(hpo_all)}. "
        f"Trigger patterns: {', '.join(profile.trigger_patterns)}. "
        f"Biomarkers: {', '.join(profile.key_biomarkers)}. "
        f"Demographics: {profile.demographics}. "
        f"Comorbidities: {', '.join(profile.common_comorbidities)}."
    )


@lru_cache(maxsize=1)
def _get_collection() -> chromadb.Collection:
    """Return (or build) the ChromaDB collection. Cached after first call."""
    _CHROMA_PATH.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(_CHROMA_PATH))
    ef = embedding_functions.DefaultEmbeddingFunction()

    collection = client.get_or_create_collection(
        name=_COLLECTION_NAME,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )

    if collection.count() == 0:
        logger.info("Knowledge base empty — building from %s", _PROFILES_PATH.name)
        _build_collection(collection)

    return collection


def _build_collection(collection: chromadb.Collection) -> None:
    profiles = _load_profiles()
    documents = [_profile_to_document(p) for p in profiles]
    ids = [p.condition_id for p in profiles]
    metadatas = [
        {
            "name": p.name,
            "specialist_type": p.specialist_type,
            "cardinal_hpo": ",".join(p.cardinal_hpo_terms),
            "supportive_hpo": ",".join(p.supportive_hpo_terms),
            "condition_id": p.condition_id,
        }
        for p in profiles
    ]
    collection.add(documents=documents, ids=ids, metadatas=metadatas)
    logger.info("Knowledge base built: %d profiles indexed", len(profiles))


def build_knowledge_base() -> None:
    """Explicitly build (or rebuild) the knowledge base. Called at startup."""
    _get_collection.cache_clear()
    _get_collection()


def search_by_fingerprint(
    hpo_ids: list[str],
    trigger_texts: list[str],
    ehr_conditions: list[str],
    top_k: int = 5,
) -> list[RareDiseaseProfile]:
    """
    Search the knowledge base for the top-K most similar disease profiles
    given the patient's symptom fingerprint.

    Returns RareDiseaseProfile objects sorted by similarity (best first).
    """
    if not hpo_ids and not trigger_texts and not ehr_conditions:
        logger.warning("search_by_fingerprint called with empty query — returning empty list")
        return []

    # Build query string from patient fingerprint
    query_parts: list[str] = []
    if hpo_ids:
        query_parts.append(f"HPO terms: {', '.join(hpo_ids)}")
    if trigger_texts:
        query_parts.append(f"Triggers: {', '.join(trigger_texts)}")
    if ehr_conditions:
        query_parts.append(f"Known conditions: {', '.join(ehr_conditions)}")
    query = ". ".join(query_parts)

    collection = _get_collection()
    actual_top_k = min(top_k, collection.count())
    if actual_top_k == 0:
        return []

    results = collection.query(
        query_texts=[query],
        n_results=actual_top_k,
        include=["metadatas", "distances"],
    )

    if not results or not results["ids"] or not results["ids"][0]:
        return []

    # Map back to full profiles
    all_profiles = {p.condition_id: p for p in _load_profiles()}
    returned_ids: list[str] = results["ids"][0]
    matched = [all_profiles[cid] for cid in returned_ids if cid in all_profiles]

    logger.info(
        "Knowledge base search returned %d profiles for query (top_k=%d)",
        len(matched),
        top_k,
    )
    return matched


def get_all_profiles() -> list[RareDiseaseProfile]:
    """Return all profiles (for validation and testing)."""
    return _load_profiles()
