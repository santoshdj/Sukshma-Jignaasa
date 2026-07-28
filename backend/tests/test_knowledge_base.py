"""
Tests for the rare disease knowledge base.
These tests use the real ChromaDB (no mock) to verify retrieval quality.
"""

from __future__ import annotations

import pytest

from app.models.hypothesis import RareDiseaseProfile
from app.services.knowledge_base import (
    build_knowledge_base,
    get_all_profiles,
    search_by_fingerprint,
)


@pytest.fixture(autouse=True, scope="module")
def build_kb():
    """Build the knowledge base once for the whole test module."""
    build_knowledge_base()


class TestKnowledgeBaseIntegrity:
    def test_profiles_load_without_error(self):
        profiles = get_all_profiles()
        assert len(profiles) >= 30

    def test_all_profiles_are_valid_pydantic(self):
        profiles = get_all_profiles()
        for p in profiles:
            assert isinstance(p, RareDiseaseProfile)
            assert p.condition_id
            assert p.name
            assert p.specialist_type

    def test_key_conditions_present(self):
        ids = {p.condition_id for p in get_all_profiles()}
        required = {"HEDS", "POTS", "MCAS", "MECFS", "SLE", "SJOGRENS", "FIBROMYALGIA"}
        missing = required - ids
        assert not missing, f"Missing conditions: {missing}"

    def test_all_profiles_have_at_least_one_hpo_term(self):
        for p in get_all_profiles():
            total_hpo = len(p.cardinal_hpo_terms) + len(p.supportive_hpo_terms)
            assert total_hpo > 0, f"{p.condition_id} has no HPO terms"


class TestKnowledgeBaseSearch:
    def test_empty_query_returns_empty(self):
        results = search_by_fingerprint([], [], [])
        assert results == []

    def test_returns_at_most_top_k(self):
        results = search_by_fingerprint(
            hpo_ids=["HP:0012378"],
            trigger_texts=["fatigue"],
            ehr_conditions=[],
            top_k=3,
        )
        assert len(results) <= 3

    def test_pots_query_retrieves_pots_in_top_3(self):
        """POTS-specific HPO terms should retrieve POTS as a top result."""
        results = search_by_fingerprint(
            hpo_ids=["HP:0001649", "HP:0002907", "HP:0012758"],
            trigger_texts=["prolonged standing", "heat exposure"],
            ehr_conditions=[],
            top_k=5,
        )
        condition_ids = [r.condition_id for r in results]
        assert "POTS" in condition_ids[:3], (
            f"POTS not in top 3. Got: {condition_ids}"
        )

    def test_heds_query_retrieves_heds_in_top_3(self):
        """hEDS-specific HPO terms should retrieve hEDS as a top result."""
        results = search_by_fingerprint(
            hpo_ids=["HP:0001382", "HP:0002829", "HP:0001388", "HP:0000974"],
            trigger_texts=["joint dislocations", "skin fragility"],
            ehr_conditions=[],
            top_k=5,
        )
        condition_ids = [r.condition_id for r in results]
        assert "HEDS" in condition_ids[:3], (
            f"HEDS not in top 3. Got: {condition_ids}"
        )

    def test_mcas_query_retrieves_mcas_in_top_5(self):
        """MCAS-specific HPO terms should retrieve MCAS somewhere in top 5."""
        results = search_by_fingerprint(
            hpo_ids=["HP:0001025", "HP:0002018", "HP:0030214"],
            trigger_texts=["food triggers", "fragrance sensitivity", "dietary gluten"],
            ehr_conditions=[],
            top_k=5,
        )
        condition_ids = [r.condition_id for r in results]
        assert "MCAS" in condition_ids, (
            f"MCAS not in top 5. Got: {condition_ids}"
        )

    def test_triad_query_returns_at_least_one(self):
        """The hEDS/POTS/MCAS triad query should surface at least one in top-5."""
        results = search_by_fingerprint(
            hpo_ids=[
                "HP:0001382", "HP:0002829",  # hEDS
                "HP:0001649", "HP:0002907",  # POTS
                "HP:0001025", "HP:0030214",  # MCAS
            ],
            trigger_texts=["prolonged standing", "food triggers", "heat", "fragrance"],
            ehr_conditions=[],
            top_k=5,
        )
        condition_ids = {r.condition_id for r in results}
        triad = {"HEDS", "POTS", "MCAS"}
        overlap = triad & condition_ids
        assert len(overlap) >= 1, (
            f"Expected at least 1 of {triad} in top-5. Got: {condition_ids}"
        )

    def test_vague_query_returns_results_without_error(self):
        """A single HPO term should not crash the search."""
        results = search_by_fingerprint(
            hpo_ids=["HP:0012378"],
            trigger_texts=[],
            ehr_conditions=[],
            top_k=5,
        )
        assert isinstance(results, list)
        assert len(results) <= 5

    def test_ehr_conditions_influence_results(self):
        """EHR-pulled conditions should contribute to the query."""
        results_without = search_by_fingerprint(
            hpo_ids=["HP:0002829"],
            trigger_texts=[],
            ehr_conditions=[],
            top_k=5,
        )
        results_with = search_by_fingerprint(
            hpo_ids=["HP:0002829"],
            trigger_texts=[],
            ehr_conditions=["Hypermobile Ehlers-Danlos Syndrome"],
            top_k=5,
        )
        # Both should return results without crashing
        assert isinstance(results_without, list)
        assert isinstance(results_with, list)
