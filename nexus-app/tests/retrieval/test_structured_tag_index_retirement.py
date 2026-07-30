"""Structured domains must not bypass the retired tag-index boundary."""

import pytest

from nexus_app.retrieval.domain_registry import DOMAIN_REGISTRY
from nexus_app.retrieval.executors.job_demand import JobDemandRetrievalExecutor
from nexus_app.retrieval.schemas import BusinessDomain, RetrievalSubQuery
from nexus_app.retrieval.sql_guardrails import StructuredPlanGuardrailError
from nexus_app.retrieval.tag_schemas import TagFilter


def test_structured_profiles_do_not_allow_tag_filters() -> None:
    for domain in (
        BusinessDomain.JOB_DEMAND,
        BusinessDomain.MAJOR_DISTRIBUTION,
        BusinessDomain.COMPETENCY_ANALYSIS,
    ):
        assert all(not profile.allowed_tag_types for profile in DOMAIN_REGISTRY[domain].query_profiles)
        assert all(profile.tag_target_type is None for profile in DOMAIN_REGISTRY[domain].query_profiles)


def test_direct_structured_executor_rejects_retired_tag_filters(session) -> None:
    query = RetrievalSubQuery.model_validate({
        "query_id": "q", "channel": "structured", "domain": "job_demand",
        "purpose": "test", "query_text": "北京岗位",
        "structured_plan": {
            "table_profile": "job_demand.v1",
            "query_profile": "job_demand.record_list",
        },
        "tag_filters": {"regions": TagFilter(tags=["北京"]).model_dump()},
    })

    with pytest.raises(StructuredPlanGuardrailError, match="not allowed"):
        JobDemandRetrievalExecutor().execute(session, query)
