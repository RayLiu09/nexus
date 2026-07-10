"""Guardrails for structured retrieval plans.

The planner may describe *what* to query, but execution only proceeds after the
plan is checked against registered query profiles and field whitelists.

v1.3 Sprint N.2 additions:

* ``validate_tag_filters`` — enforces that every ``tag_filters`` bucket
  in a ``RetrievalSubQuery`` is on the current query profile's
  ``allowed_tag_types`` list.  Blocks F2-4 (unrelated domain gets a tag
  filter that pollutes its result set).
* ``TARGET_ID_IN_KEY`` — reserved ``structured_filters`` slot the
  Resolver-driven executor uses to inject a target-id ``IN (...)`` set
  (F6-1 / F6-2 protection).  ``_ensure_allowed_filters`` treats this
  key as always-allowed for profiles that opt into ``id_in_supported``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from nexus_app.retrieval.domain_registry import QueryProfile, get_query_profile
from nexus_app.retrieval.schemas import BusinessDomain, StructuredPlan


# Reserved key the Resolver-driven executor may drop into
# ``structured_filters`` to smuggle a target-id IN set.  Kept as a
# double-underscore sentinel so a real column name can never collide.
TARGET_ID_IN_KEY: str = "__target_id_in__"


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


def validate_tag_filters(
    *,
    domain: BusinessDomain | str,
    tag_filters: Mapping[str, Any],
    query_profile_key: str | None = None,
) -> QueryProfile:
    """Reject any ``tag_filters`` key that is not on the profile's
    ``allowed_tag_types`` list.

    Called by the orchestrator once per sub_query, before dispatching to
    the Resolver / executor pair.  Returns the resolved ``QueryProfile``
    so the caller doesn't need a second lookup.

    Empty ``tag_filters`` is always fine.  A profile with an empty
    ``allowed_tag_types`` tuple is treated as "no tag_filters permitted"
    — any incoming key raises.

    F2-3 (tag_filters vs structured_filters column-name collision) is
    caught downstream by the executor when it merges the two dicts.
    """
    query_profile = get_query_profile(domain, query_profile_key)
    if not tag_filters:
        return query_profile

    allowed = set(query_profile.allowed_tag_types)
    disallowed = [key for key in tag_filters if key not in allowed]
    if disallowed:
        raise StructuredPlanGuardrailError(
            f"tag_filters bucket(s) {sorted(disallowed)!r} not allowed on "
            f"profile {query_profile.key!r}; allowed_tag_types="
            f"{tuple(sorted(allowed))!r}"
        )
    return query_profile


def _ensure_allowed_filters(plan: StructuredPlan, query_profile: QueryProfile) -> None:
    allowed = set(query_profile.allowed_filters)
    for key in plan.filters:
        # ``__target_id_in__`` is Resolver-driven and reserved; allow it
        # only when the profile advertises ``id_in_supported=True`` so
        # unstructured/hybrid profiles that expect a different filter
        # surface don't accidentally accept it.
        if key == TARGET_ID_IN_KEY:
            if not query_profile.id_in_supported:
                raise StructuredPlanGuardrailError(
                    f"filter key {TARGET_ID_IN_KEY!r} is reserved for "
                    "id IN-set injection but this profile does not "
                    "support it (id_in_supported=False)"
                )
            continue
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

