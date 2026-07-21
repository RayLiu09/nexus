"""v2 retrieval audit summary schema (§10 阶段 A A6 + §1.15 additions).

Query Router v2.0 threads more context through `SearchQueryExecuted` /
`QAAnswerGenerated` events than v1 did. `audit_log.summary` is a free
JSON column so no migration is required; this module gives the phase-B
dispatcher / composer a canonical builder + field checklist so nobody
has to remember the field list from a doc.

Field names are frozen — treat them as an API contract to downstream
analytics. Adding a field is fine; renaming or removing one requires a
new field or a migration on the read side.
"""
from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

# Fixed enum values used by dispatcher / composer at runtime.

CallerType = Literal["console_session", "api_caller"]

RouteType = Literal[
    # v2 canonical routes (phase B onwards)
    "internal_query",
    "open_query",
    # Legacy retrieval routes retained for /open/v1/search & /qa audits
    # so v1 & v2 rows share the same summary shape.
    "search",
    "qa",
]

IntentType = Literal[
    "scenario_1",
    "scenario_2",
    "scenario_3",
    "scenario_4",
    "scenario_5",
    "unknown",
]

DispatchFallback = Literal[
    "no_tool_call",           # LLM returned zero tool_calls → unknown fallback
    "param_validation_failed",  # Pydantic tool_call params rejected
]

ExpandQueriesStatus = Literal[
    "true",                   # expansion succeeded
    "false",                  # expansion not requested
    "false_due_to_error",     # expansion requested but LLM call failed
]


class RetrievalV2SummaryFields(TypedDict, total=False):
    """v2 retrieval-specific fields added on top of existing audit summaries.

    Every field is optional (`total=False`) — v1 events won't populate
    them and phase-B events populate only the fields relevant to the
    round-trip that produced them.
    """

    # --- identity + routing ---
    route: RouteType
    caller_type: CallerType

    # --- Layer 1 intent classifier output ---
    intent: IntentType | None
    intent_confidence: float | None

    # --- Layer 2 dispatcher ---
    invoked_tools: list[str]
    missing_optional_params: list[str]
    dispatch_fallback: DispatchFallback | None  # §1.11 决策 #4

    # --- Layer 3 composer ---
    generated_ratio: float | None
    template_id: str | None                     # scenario_5 模板 id

    # --- A4 chart adapter / composer (§1.15 §7.3) ---
    chart_hallucination_ids: list[str]
    chart_unused_ids: list[str]

    # --- A5 同义 query 生成 (§1.15 §4.2.6) ---
    matched_queries: list[str] | None
    expand_queries_status: ExpandQueriesStatus | None

    # --- request-scoped public-web fallback ---
    online_search_requested: bool
    web_search_provider: str | None
    external_result_count: int
    external_result_domains: list[str]
    external_search_latency_ms: float | None
    external_search_error_type: str | None

    # --- versioning marker for future audit-analytics migrations ---
    query_route: Literal["v2"]


def build_retrieval_v2_summary(
    *,
    base: dict[str, Any] | None = None,
    fields: RetrievalV2SummaryFields | None = None,
) -> dict[str, Any]:
    """Merge a v1-shape base summary with v2 additions.

    Preserves whatever the caller already produced (query_hash, kb, etc.)
    and layers the v2 fields on top. Callers that skip a v2 field just
    omit it from the dict — no None-flood in the output.
    """
    merged: dict[str, Any] = dict(base or {})
    if fields:
        for key, value in fields.items():
            # Skip explicit-None entries so summaries stay compact; a real
            # None value is still allowed by using ``base`` directly.
            if value is None and key not in {"intent", "intent_confidence",
                                             "dispatch_fallback", "matched_queries",
                                             "expand_queries_status", "template_id",
                                             "generated_ratio"}:
                continue
            merged[key] = value
    return merged


__all__ = [
    "CallerType",
    "DispatchFallback",
    "ExpandQueriesStatus",
    "IntentType",
    "RetrievalV2SummaryFields",
    "RouteType",
    "build_retrieval_v2_summary",
]
