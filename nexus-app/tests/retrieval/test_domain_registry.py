from __future__ import annotations

import pytest

from nexus_app.retrieval.domain_registry import (
    domains_for_channel,
    get_domain_definition,
    get_query_profile,
    list_domain_definitions,
)
from nexus_app.retrieval.schemas import BusinessDomain, RetrievalChannel


def test_registry_contains_first_batch_domains():
    domains = {definition.domain for definition in list_domain_definitions()}

    assert domains == {
        "course_textbook",
        "major_profile",
        "major_distribution",
        "job_demand",
        "competency_analysis",
    }


def test_course_textbook_defaults_to_unstructured_pgvector():
    definition = get_domain_definition(BusinessDomain.COURSE_TEXTBOOK)

    assert definition.default_channel == RetrievalChannel.UNSTRUCTURED
    assert definition.executor_key == "unstructured_pgvector"
    assert definition.get_query_profile().key == "semantic_chunk"


def test_major_distribution_registry_exposes_structured_query_profiles():
    definition = get_domain_definition("major_distribution")
    trend = get_query_profile("major_distribution", "major_distribution.trend_by_year")

    assert definition.default_channel == RetrievalChannel.STRUCTURED
    assert definition.executor_key == "major_distribution_sql"
    assert trend.table_profile == "major_distribution.v1"
    assert "year" in trend.allowed_group_by
    assert "major_name" in trend.allowed_filters
    assert "sum:distribution_count" in trend.allowed_metrics


def test_domains_for_channel_includes_hybrid_major_profile():
    structured_domains = {definition.domain for definition in domains_for_channel("structured")}
    hybrid_domains = {definition.domain for definition in domains_for_channel(RetrievalChannel.HYBRID)}

    assert "major_distribution" in structured_domains
    assert "job_demand" in structured_domains
    assert "competency_analysis" in structured_domains
    assert hybrid_domains == {"major_profile"}


def test_unknown_domain_or_profile_fails_closed():
    with pytest.raises(KeyError):
        get_domain_definition("evidence_graph")

    with pytest.raises(KeyError):
        get_query_profile("major_distribution", "raw_sql")

