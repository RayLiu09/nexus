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
