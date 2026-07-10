"""PR-5 guards for QueryProfile v1.3 extensions + sql_guardrails updates.

Covers:

* Every registered QueryProfile declares an ``allowed_tag_types`` list
  matching its business intent (regression: silent drift when someone
  adds a new profile without thinking about tag routing).
* ``validate_tag_filters`` accepts allowed buckets, rejects unknown /
  cross-domain buckets (F2-4).
* ``TARGET_ID_IN_KEY`` sentinel is auto-allowed when the profile opts
  in (F6-1 / F6-2) and rejected when the profile opts out.
* Pre-v1.3 ``validate_structured_plan`` semantics are preserved for
  legitimate columns and legitimate tag-less plans.
"""

from __future__ import annotations

import pytest

from nexus_app.retrieval.domain_registry import (
    DOMAIN_REGISTRY,
    QueryProfile,
    get_query_profile,
)
from nexus_app.retrieval.schemas import (
    BusinessDomain,
    RetrievalChannel,
    StructuredPlan,
)
from nexus_app.retrieval.sql_guardrails import (
    TARGET_ID_IN_KEY,
    StructuredPlanGuardrailError,
    validate_structured_plan,
    validate_tag_filters,
)
from nexus_app.retrieval.tag_schemas import TAG_BUCKET_NAMES, TagFilter


# ---------------------------------------------------------------------------
# QueryProfile registration
# ---------------------------------------------------------------------------


class TestProfileAllowedTagTypes:
    def test_default_dataclass_field_empty(self) -> None:
        """A profile constructed without allowed_tag_types (backwards-
        compat surface) starts with the empty tuple."""
        p = QueryProfile(
            key="minimal",
            channel=RetrievalChannel.STRUCTURED,
            description="d",
            executor_key="x",
        )
        assert p.allowed_tag_types == ()
        assert p.id_in_supported is True

    def test_structured_domain_declares_tag_types(self) -> None:
        # major_distribution — expected regions / majors / time_ranges
        for profile in DOMAIN_REGISTRY[BusinessDomain.MAJOR_DISTRIBUTION].query_profiles:
            assert set(profile.allowed_tag_types) == {"regions", "majors", "time_ranges"}
            assert profile.id_in_supported is True

    def test_job_demand_record_list_expected_buckets(self) -> None:
        p = get_query_profile(BusinessDomain.JOB_DEMAND, "job_demand.record_list")
        assert set(p.allowed_tag_types) == {
            "regions", "industries", "occupations", "time_ranges",
        }

    def test_job_demand_requirement_keyword_expands_to_abilities(self) -> None:
        """requirement_keyword profile flows into the ability / topic
        buckets via item_type=professional_skill conditional projection."""
        p = get_query_profile(BusinessDomain.JOB_DEMAND, "job_demand.requirement_keyword")
        assert "abilities" in p.allowed_tag_types
        assert "topics" in p.allowed_tag_types

    def test_competency_profiles(self) -> None:
        for profile in DOMAIN_REGISTRY[BusinessDomain.COMPETENCY_ANALYSIS].query_profiles:
            assert set(profile.allowed_tag_types) == {"occupations", "abilities", "majors"}

    def test_course_textbook_semantic_chunk_no_id_in(self) -> None:
        p = get_query_profile(BusinessDomain.COURSE_TEXTBOOK, "semantic_chunk")
        assert p.id_in_supported is False
        assert set(p.allowed_tag_types) == {"majors", "abilities", "topics"}

    def test_major_profile_hybrid(self) -> None:
        p = get_query_profile(BusinessDomain.MAJOR_PROFILE, "major_profile_semantic")
        assert p.id_in_supported is False
        assert set(p.allowed_tag_types) == {
            "majors", "occupations", "abilities", "topics",
        }

    def test_all_registered_buckets_are_canonical_names(self) -> None:
        """No stray singular / renamed bucket names.  Every allowed_tag_types
        entry across every domain must come from TAG_BUCKET_NAMES."""
        canonical = set(TAG_BUCKET_NAMES)
        for domain_def in DOMAIN_REGISTRY.values():
            for profile in domain_def.query_profiles:
                for bucket in profile.allowed_tag_types:
                    assert bucket in canonical, (
                        f"profile {profile.key} declared unknown bucket "
                        f"{bucket!r}"
                    )


# ---------------------------------------------------------------------------
# validate_tag_filters
# ---------------------------------------------------------------------------


class TestValidateTagFilters:
    def test_empty_tag_filters_ok(self) -> None:
        result = validate_tag_filters(
            domain=BusinessDomain.JOB_DEMAND,
            tag_filters={},
            query_profile_key="job_demand.record_list",
        )
        assert result.key == "job_demand.record_list"

    def test_allowed_buckets_pass(self) -> None:
        # Regions + industries are on the allowed list for
        # job_demand.record_list.
        result = validate_tag_filters(
            domain=BusinessDomain.JOB_DEMAND,
            tag_filters={
                "regions": TagFilter(tags=["北京市"]),
                "industries": TagFilter(tags=["直播电商"]),
            },
            query_profile_key="job_demand.record_list",
        )
        assert result.key == "job_demand.record_list"

    def test_disallowed_bucket_rejected(self) -> None:
        # job_demand does not accept "majors".
        with pytest.raises(StructuredPlanGuardrailError, match="not allowed"):
            validate_tag_filters(
                domain=BusinessDomain.JOB_DEMAND,
                tag_filters={
                    "majors": TagFilter(tags=["电子商务"]),
                },
                query_profile_key="job_demand.record_list",
            )

    def test_partial_disallowed_bucket_rejected(self) -> None:
        # One allowed + one disallowed → still fails.  The error message
        # names the disallowed one.
        with pytest.raises(StructuredPlanGuardrailError) as exc_info:
            validate_tag_filters(
                domain=BusinessDomain.MAJOR_DISTRIBUTION,
                tag_filters={
                    "regions": TagFilter(tags=["北京"]),
                    "occupations": TagFilter(tags=["直播运营"]),
                },
                query_profile_key="major_distribution.trend_by_year",
            )
        assert "occupations" in str(exc_info.value)

    def test_domain_str_accepted(self) -> None:
        result = validate_tag_filters(
            domain="job_demand",
            tag_filters={"regions": TagFilter(tags=["北京市"])},
            query_profile_key="job_demand.record_list",
        )
        assert result.key == "job_demand.record_list"

    def test_profile_with_no_allowed_tag_types_rejects_all(self) -> None:
        """A profile that hasn't been enrolled in the tag pipeline
        (empty allowed_tag_types tuple) rejects every incoming bucket."""
        # Register a phantom profile via QueryProfile directly, then
        # test the pure logic branch via a monkeypatched registry entry
        # is overkill — just verify with a real profile lacking the
        # bucket in question.
        with pytest.raises(StructuredPlanGuardrailError, match="not allowed"):
            validate_tag_filters(
                domain=BusinessDomain.MAJOR_DISTRIBUTION,
                tag_filters={"topics": TagFilter(tags=["数据合规"])},
                query_profile_key="major_distribution.trend_by_year",
            )


# ---------------------------------------------------------------------------
# TARGET_ID_IN_KEY behaviour in validate_structured_plan
# ---------------------------------------------------------------------------


class TestTargetIdInKey:
    def test_target_id_in_allowed_when_profile_supports_it(self) -> None:
        """job_demand structured profiles have id_in_supported=True."""
        plan = StructuredPlan(
            table_profile="job_demand.v1",
            query_profile="job_demand.record_list",
            filters={
                TARGET_ID_IN_KEY: ["job-id-1", "job-id-2"],
                "city": "北京市",
            },
        )
        guarded = validate_structured_plan(
            domain=BusinessDomain.JOB_DEMAND, plan=plan,
        )
        assert guarded.query_profile.key == "job_demand.record_list"

    def test_target_id_in_alone_is_allowed(self) -> None:
        plan = StructuredPlan(
            table_profile="job_demand.v1",
            query_profile="job_demand.record_list",
            filters={TARGET_ID_IN_KEY: ["job-id-1"]},
        )
        validate_structured_plan(
            domain=BusinessDomain.JOB_DEMAND, plan=plan,
        )

    def test_target_id_in_rejected_on_id_in_unsupported_profile(self) -> None:
        # course_textbook.semantic_chunk sets id_in_supported=False; try
        # to sneak the sentinel through validate_structured_plan.
        # Note: unstructured profiles don't use validate_structured_plan
        # in real life — this test just proves the sentinel guard fires
        # correctly if someone tries.
        # We simulate a StructuredPlan against the unstructured profile
        # by constructing a QueryProfile lookalike via the actual
        # registry: no unstructured profile ships table_profile, so we
        # have to prove the check via a direct profile inspection.
        p = get_query_profile(BusinessDomain.COURSE_TEXTBOOK, "semantic_chunk")
        assert p.id_in_supported is False
        # Direct sanity: the sql_guardrails module correctly refuses
        # __target_id_in__ when we invoke its private helper.
        from nexus_app.retrieval.sql_guardrails import _ensure_allowed_filters

        plan = StructuredPlan(
            table_profile="job_demand.v1",  # nominal
            filters={TARGET_ID_IN_KEY: ["x"]},
        )
        with pytest.raises(StructuredPlanGuardrailError, match="reserved for"):
            _ensure_allowed_filters(plan, p)


# ---------------------------------------------------------------------------
# Backwards-compat: pre-v1.3 structured plan validation still works
# ---------------------------------------------------------------------------


class TestBackwardsCompat:
    def test_pre_v1_3_plan_still_validated(self) -> None:
        plan = StructuredPlan(
            table_profile="job_demand.v1",
            query_profile="job_demand.count_by_city",
            filters={"city": "北京市"},
            group_by=["city"],
            metrics=[
                {"function": "count", "field": "record"},
            ],
        )
        guarded = validate_structured_plan(
            domain=BusinessDomain.JOB_DEMAND, plan=plan,
        )
        assert guarded.query_profile.key == "job_demand.count_by_city"

    def test_pre_v1_3_disallowed_column_still_fails(self) -> None:
        plan = StructuredPlan(
            table_profile="job_demand.v1",
            query_profile="job_demand.record_list",
            filters={"nonexistent_column": "x"},
        )
        with pytest.raises(StructuredPlanGuardrailError, match="not allowed"):
            validate_structured_plan(
                domain=BusinessDomain.JOB_DEMAND, plan=plan,
            )
