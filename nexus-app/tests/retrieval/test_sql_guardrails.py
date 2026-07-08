from __future__ import annotations

import pytest

from nexus_app.retrieval.schemas import QueryMetric, QueryOrder, StructuredPlan
from nexus_app.retrieval.sql_guardrails import (
    StructuredPlanGuardrailError,
    validate_structured_plan,
)


def test_major_distribution_trend_plan_passes_guardrails():
    guarded = validate_structured_plan(
        domain="major_distribution",
        plan=StructuredPlan(
            table_profile="major_distribution.v1",
            query_profile="major_distribution.trend_by_year",
            filters={"major_name": "电子商务", "education_level": "高职"},
            group_by=["year"],
            metrics=[QueryMetric(field="distribution_count", function="sum")],
            order_by=[QueryOrder(field="year", direction="asc")],
            limit=50,
        ),
    )

    assert guarded.query_profile.key == "major_distribution.trend_by_year"
    assert guarded.limit == 50


def test_unknown_query_profile_fails_closed():
    with pytest.raises(KeyError):
        validate_structured_plan(
            domain="major_distribution",
            plan=StructuredPlan(
                table_profile="major_distribution.v1",
                query_profile="major_distribution.raw_sql",
            ),
        )


def test_job_demand_city_count_plan_passes_guardrails():
    guarded = validate_structured_plan(
        domain="job_demand",
        plan=StructuredPlan(
            table_profile="job_demand.v1",
            query_profile="job_demand.count_by_city",
            filters={"industry_name": "互联网"},
            group_by=["city"],
            metrics=[QueryMetric(field="job_count", function="sum")],
            order_by=[QueryOrder(field="city", direction="asc")],
        ),
    )

    assert guarded.query_profile.key == "job_demand.count_by_city"


def test_competency_category_plan_passes_guardrails():
    guarded = validate_structured_plan(
        domain="competency_analysis",
        plan=StructuredPlan(
            table_profile="ability_analysis.pgsd.v1",
            query_profile="competency.ability_items_by_category",
            group_by=["ability_major_category_code"],
            metrics=[QueryMetric(field="record", function="count")],
        ),
    )

    assert guarded.query_profile.key == "competency.ability_items_by_category"


def test_competency_task_tree_rejects_relation_only_filter():
    with pytest.raises(StructuredPlanGuardrailError, match="filter field"):
        validate_structured_plan(
            domain="competency_analysis",
            plan=StructuredPlan(
                table_profile="ability_analysis.pgsd.v1",
                query_profile="competency.task_tree",
                filters={"relation_type": "WORK_CONTENT_REQUIRES_ABILITY"},
            ),
        )


def test_competency_relation_plan_accepts_relation_fields():
    guarded = validate_structured_plan(
        domain="competency_analysis",
        plan=StructuredPlan(
            table_profile="ability_analysis.pgsd.v1",
            query_profile="competency.relations_by_ability",
            filters={
                "relation_type": "WORK_CONTENT_REQUIRES_ABILITY",
                "source_type": "work_content",
                "target_type": "ability_item",
            },
        ),
    )

    assert guarded.query_profile.key == "competency.relations_by_ability"


def test_non_whitelisted_filter_fails_closed():
    with pytest.raises(StructuredPlanGuardrailError, match="filter field"):
        validate_structured_plan(
            domain="major_distribution",
            plan=StructuredPlan(
                table_profile="major_distribution.v1",
                query_profile="major_distribution.trend_by_year",
                filters={"school_name": "某学校"},
            ),
        )


def test_non_whitelisted_order_by_fails_closed():
    with pytest.raises(StructuredPlanGuardrailError, match="order_by field"):
        validate_structured_plan(
            domain="major_distribution",
            plan=StructuredPlan(
                table_profile="major_distribution.v1",
                query_profile="major_distribution.trend_by_year",
                order_by=[QueryOrder(field="source_row_no", direction="asc")],
            ),
        )


def test_non_whitelisted_metric_fails_closed():
    with pytest.raises(StructuredPlanGuardrailError, match="metric"):
        validate_structured_plan(
            domain="major_distribution",
            plan=StructuredPlan(
                table_profile="major_distribution.v1",
                query_profile="major_distribution.trend_by_year",
                metrics=[QueryMetric(field="year", function="avg")],
            ),
        )


def test_over_limit_fails_closed():
    plan = StructuredPlan(
        table_profile="major_distribution.v1",
        query_profile="major_distribution.record_list",
        limit=200,
    )
    plan.limit = 201

    with pytest.raises(StructuredPlanGuardrailError, match="exceeds"):
        validate_structured_plan(
            domain="major_distribution",
            plan=plan,
        )
