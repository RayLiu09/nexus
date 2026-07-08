"""Guardrails for structured retrieval plans.

The planner may describe *what* to query, but execution only proceeds after the
plan is checked against registered query profiles and field whitelists.
"""
from __future__ import annotations

from dataclasses import dataclass

from nexus_app.retrieval.domain_registry import QueryProfile, get_query_profile
from nexus_app.retrieval.schemas import BusinessDomain, StructuredPlan


class StructuredPlanGuardrailError(ValueError):
    """Raised when a structured retrieval plan violates query guardrails."""


@dataclass(frozen=True)
class GuardedStructuredPlan:
    domain: BusinessDomain
    query_profile: QueryProfile
    plan: StructuredPlan
    limit: int


def validate_structured_plan(
    *,
    domain: BusinessDomain | str,
    plan: StructuredPlan,
) -> GuardedStructuredPlan:
    query_profile = get_query_profile(domain, plan.query_profile)
    domain_key = domain if isinstance(domain, BusinessDomain) else BusinessDomain(domain)
    if query_profile.table_profile and plan.table_profile != query_profile.table_profile:
        raise StructuredPlanGuardrailError(
            f"table_profile {plan.table_profile!r} does not match registered profile "
            f"{query_profile.table_profile!r}"
        )
    _ensure_allowed_filters(plan, query_profile)
    _ensure_allowed_group_by(plan, query_profile)
    _ensure_allowed_metrics(plan, query_profile)
    _ensure_allowed_order_by(plan, query_profile)
    if plan.limit > query_profile.max_limit:
        raise StructuredPlanGuardrailError(
            f"limit {plan.limit} exceeds max_limit {query_profile.max_limit}"
        )
    return GuardedStructuredPlan(
        domain=domain_key,
        query_profile=query_profile,
        plan=plan,
        limit=min(plan.limit, query_profile.max_limit),
    )


def _ensure_allowed_filters(plan: StructuredPlan, query_profile: QueryProfile) -> None:
    allowed = set(query_profile.allowed_filters)
    for key in plan.filters:
        if key not in allowed:
            raise StructuredPlanGuardrailError(f"filter field {key!r} is not allowed")


def _ensure_allowed_group_by(plan: StructuredPlan, query_profile: QueryProfile) -> None:
    allowed = set(query_profile.allowed_group_by)
    for key in plan.group_by:
        if key not in allowed:
            raise StructuredPlanGuardrailError(f"group_by field {key!r} is not allowed")


def _ensure_allowed_metrics(plan: StructuredPlan, query_profile: QueryProfile) -> None:
    allowed = set(query_profile.allowed_metrics)
    if not allowed and plan.metrics:
        raise StructuredPlanGuardrailError("metrics are not allowed for this query profile")
    for metric in plan.metrics:
        metric_key = f"{metric.function}:{metric.field}"
        if metric_key not in allowed:
            raise StructuredPlanGuardrailError(f"metric {metric_key!r} is not allowed")


def _ensure_allowed_order_by(plan: StructuredPlan, query_profile: QueryProfile) -> None:
    allowed = set(query_profile.allowed_filters) | set(query_profile.allowed_group_by)
    for order in plan.order_by:
        if order.field not in allowed:
            raise StructuredPlanGuardrailError(f"order_by field {order.field!r} is not allowed")

