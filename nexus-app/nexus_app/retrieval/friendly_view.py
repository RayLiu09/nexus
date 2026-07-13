"""Builder for ``RetrievalPlan.friendly_view`` — v1.3 §5.5 R3-c contract.

Produces a :class:`FriendlyRetrievalPlanView` from an ``(intent, plan)``
pair using ``display_labels`` for every Chinese string, so the frontend
never derives labels client-side.

The builder runs **pre-execution** — ``sub_query_cards[*].result_summary``
stays ``None`` until executors report back.  Post-execution enrichment
(hit_count, duration_ms, evidence_strength, match_layer_summary) is a
follow-up: it needs access to the concrete :class:`RetrievalResult`
list which only exists after the orchestrator's DAG runs.  Cards
therefore render with status="pending" during the ``/plans`` preview
and get overwritten (or left as-is on frontend) once the ``/query``
response returns.

Contract:

* Every call returns a fully-populated :class:`FriendlyRetrievalPlanView`
  — never raises for a well-formed plan.  Missing labels fall back to
  the raw code rather than blocking the response — the frontend still
  shows *something* per §5.5 R3-c ("no client-side derivation").
* ``natural_language`` is a template-based restatement; it's not
  LLM-generated.  A follow-up PR can swap the template for an LLM call
  when we want variety, but the template is stable and cheap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nexus_app.retrieval.display_labels import (
    format_match_strategy_display,
    get_channel_display_label,
    get_domain_display_label,
    get_purpose_display_label,
    get_status_display_label,
    get_tag_type_display_label,
)
from nexus_app.retrieval.tag_schemas import (
    DisplayConstraint,
    DisplayFilter,
    FriendlyRetrievalPlanView,
    IntentSummary,
    OverallSummary,
    SubQueryCard,
)

if TYPE_CHECKING:  # pragma: no cover
    from nexus_app.retrieval.schemas import (
        RetrievalIntent,
        RetrievalPlan,
        RetrievalSubQuery,
    )


__all__ = ["build_friendly_view"]


# Circled numerals up to 20 — the plan cap is 8, so ①-⑧ cover normal
# cases; digits 9+ fall back to the ASCII index for safety.
_CIRCLED_NUMBERS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def _display_index(one_based_index: int) -> str:
    if 1 <= one_based_index <= len(_CIRCLED_NUMBERS):
        return _CIRCLED_NUMBERS[one_based_index - 1]
    return f"({one_based_index})"


# ---------------------------------------------------------------------------
# Intent summary
# ---------------------------------------------------------------------------


def _confidence_level(confidence: float, threshold: float) -> str:
    """Bucket the numeric confidence into high/medium/low per v1.3 §5.5.

    Thresholds mirror the intent recogniser's own gating: at or above
    ``threshold`` is ``high``; between 0.6 and ``threshold`` is
    ``medium``; anything below is ``low``.  The lower band boundary is
    0.6 so a completely unconfident (0.0) intent still surfaces as low
    rather than crashing the UI badge.
    """
    if confidence >= threshold:
        return "high"
    if confidence >= 0.6:
        return "medium"
    return "low"


def _build_natural_language(intent: "RetrievalIntent") -> str:
    """Template-based restatement of the intent for the intent card headline.

    Example: "在岗位需求与专业分布领域中，通过背景检索方式获取信息。"
    Falls back to a generic sentence when domains are unknown.
    """
    domain_labels = [
        get_domain_display_label(d, fallback=str(d))
        for d in intent.business_domains
    ]
    if not domain_labels:
        return "在未识别到具体业务领域的情况下，正在尝试通用检索。"
    joined = "、".join(domain_labels)
    return f"在{joined}领域中，围绕「{intent.question_type}」类问题进行检索。"


def _build_display_constraints(intent: "RetrievalIntent") -> list[DisplayConstraint]:
    """Extract user-visible constraints from ``intent.constraints`` +
    ``intent.cross_asset_tags``.  Each yields one DisplayConstraint chip.

    The precedence between ``constraints`` (free-form) and
    ``cross_asset_tags`` (v1.3 structured) is: cross_asset_tags wins
    when both carry the same tag_type — the structured form is more
    reliable.
    """
    out: list[DisplayConstraint] = []
    seen_labels: set[str] = set()

    # cross_asset_tags: keyed by tag_type, each carries a list of {value, ...}
    cat = getattr(intent, "cross_asset_tags", None)
    if cat is not None:
        # CrossAssetTags exposes its buckets via model_dump for the same keys
        # as the taxonomy (regions/industries/…).  Use model_dump so we don't
        # depend on the exact class shape.
        try:
            cat_dump = cat.model_dump(exclude_none=True)
        except Exception:  # noqa: BLE001 — never let the summary panic
            cat_dump = {}
        for bucket_name, entries in cat_dump.items():
            if not isinstance(entries, list) or not entries:
                continue
            # Bucket name is plural (regions); tag_type is singular (region).
            singular = bucket_name.rstrip("s") or bucket_name
            label = get_tag_type_display_label(singular, fallback=singular)
            for entry in entries:
                value, confidence = _extract_tag_value_and_confidence(entry)
                if not value:
                    continue
                chip_key = f"{label}:{value}"
                if chip_key in seen_labels:
                    continue
                seen_labels.add(chip_key)
                out.append(
                    DisplayConstraint(
                        label=label,
                        value=value,
                        confidence=confidence,
                        source_display="从问题中识别",
                    )
                )

    # constraints: free-form dict[str, Any] — surface simple string values.
    # Complex nested structures are skipped rather than serialised, so the
    # chip list stays short and readable.
    for key, value in intent.constraints.items():
        display_value = _coerce_constraint_value(value)
        if display_value is None:
            continue
        label_key = str(key)
        label = get_tag_type_display_label(label_key, fallback=label_key)
        chip_key = f"{label}:{display_value}"
        if chip_key in seen_labels:
            continue
        seen_labels.add(chip_key)
        out.append(
            DisplayConstraint(
                label=label,
                value=display_value,
                confidence=None,
                source_display="从问题中识别",
            )
        )

    return out


def _extract_tag_value_and_confidence(
    entry: Any,
) -> tuple[str | None, float | None]:
    """Handle both string-only tag entries and dict entries with metadata."""
    if isinstance(entry, str):
        stripped = entry.strip()
        return (stripped or None, None)
    if isinstance(entry, dict):
        raw_value = entry.get("value") or entry.get("tag") or entry.get("code")
        confidence = entry.get("confidence")
        if isinstance(raw_value, str):
            stripped = raw_value.strip()
            conf: float | None = None
            if isinstance(confidence, (int, float)):
                conf = float(confidence)
            return (stripped or None, conf)
    return (None, None)


def _coerce_constraint_value(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list) and value:
        parts = [
            v.strip() for v in value
            if isinstance(v, str) and v.strip()
        ]
        if parts:
            return "、".join(parts)
    return None


def _build_intent_summary(intent: "RetrievalIntent") -> IntentSummary:
    domain_labels = [
        get_domain_display_label(d, fallback=str(d))
        for d in intent.business_domains
    ]
    return IntentSummary(
        natural_language=_build_natural_language(intent),
        business_domains_display=domain_labels,
        identified_constraints=_build_display_constraints(intent),
        unresolved_terms=list(intent.unresolved_terms),
        confidence=intent.confidence,
        confidence_level=_confidence_level(
            intent.confidence, intent.confidence_threshold
        ),
        clarification_suggestions=list(intent.suggested_refinements),
    )


# ---------------------------------------------------------------------------
# Sub-query cards
# ---------------------------------------------------------------------------


def _build_filter_summary(sub: "RetrievalSubQuery") -> list[DisplayFilter]:
    """Turn ``sub.tag_filters`` into chip descriptors.

    ``TagFilter`` carries ``candidates`` + ``optional`` + optionally
    ``match_strategy``.  We render one DisplayFilter per bucket; empty
    buckets are skipped.  ``is_from_binding`` is left ``None`` here —
    planner's binding_map exposure is a follow-up.
    """
    out: list[DisplayFilter] = []
    for bucket_name, tag_filter in sub.tag_filters.items():
        # TagFilter.tags is either a static list[str] (candidate values)
        # or a single binding string like "$shared.industries" — resolved
        # by the DAG orchestrator at execution time.  For friendly_view
        # we surface the static form; binding-string form yields an
        # explanatory chip with is_from_binding=True.
        raw_tags = getattr(tag_filter, "tags", None)
        if isinstance(raw_tags, list):
            values = [str(v) for v in raw_tags if str(v).strip()]
            is_from_binding = False
            binding_source_display: str | None = None
        elif isinstance(raw_tags, str) and raw_tags.strip():
            values = []
            is_from_binding = True
            binding_source_display = raw_tags.strip()
        else:
            continue
        if not values and not is_from_binding:
            continue
        # Bucket names are plural (regions); tag_type is singular (region).
        singular = bucket_name.rstrip("s") or bucket_name
        label = get_tag_type_display_label(singular, fallback=singular)
        strategy = getattr(tag_filter, "match_strategy", "") or ""
        out.append(
            DisplayFilter(
                label=label,
                values=values,
                match_strategy_display=format_match_strategy_display(strategy),
                is_optional=bool(getattr(tag_filter, "optional", False)),
                is_from_binding=is_from_binding if is_from_binding else None,
                binding_source_display=binding_source_display,
            )
        )
    return out


def _clip_title(text: str, *, max_length: int = 80) -> str:
    stripped = text.strip() or "（未命名子查询）"
    if len(stripped) <= max_length:
        return stripped
    return stripped[: max_length - 1] + "…"


def _build_sub_query_card(
    sub: "RetrievalSubQuery",
    display_index: str,
) -> SubQueryCard:
    return SubQueryCard(
        query_id=sub.query_id,
        display_index=display_index,
        title=_clip_title(sub.query_text),
        purpose_display=get_purpose_display_label(sub.purpose),
        channel_display=get_channel_display_label(
            sub.channel.value if hasattr(sub.channel, "value") else str(sub.channel),
            fallback=str(sub.channel),
        ),
        domain_display=get_domain_display_label(sub.domain, fallback=str(sub.domain)),
        depends_on_display=list(sub.depends_on),
        filter_summary=_build_filter_summary(sub),
        status="pending",
        status_display=get_status_display_label("pending"),
        degraded_reasons=[],
        result_summary=None,
        actions_available=[],
    )


# ---------------------------------------------------------------------------
# Overall summary
# ---------------------------------------------------------------------------


def _compute_max_depth(plan: "RetrievalPlan") -> int:
    """Longest depends_on chain in the plan DAG.

    Returns 0 for a plan whose sub_queries all have empty depends_on.
    Cycle-safe: RetrievalPlan already rejects cycles at validation time,
    so this is a straightforward memoised DFS.
    """
    id_to_deps: dict[str, list[str]] = {
        sub.query_id: list(sub.depends_on) for sub in plan.sub_queries
    }
    memo: dict[str, int] = {}

    def depth_of(node_id: str) -> int:
        if node_id in memo:
            return memo[node_id]
        deps = id_to_deps.get(node_id, [])
        if not deps:
            memo[node_id] = 0
            return 0
        memo[node_id] = 1 + max(depth_of(dep) for dep in deps)
        return memo[node_id]

    if not id_to_deps:
        return 0
    return max(depth_of(node_id) for node_id in id_to_deps)


def _combine_summary(plan: "RetrievalPlan") -> str:
    """Human-readable summary of the plan's merge behaviour.

    Uses the plan's ``merge_strategy`` + the sub_queries' ``combine``
    op distribution to produce a short Chinese phrase.
    """
    if plan.merge_strategy == "evidence_chain":
        return "多步证据链合并（evidence_chain）"
    combines = {sub.combine for sub in plan.sub_queries}
    if combines == {"AND"}:
        return "所有维度均需匹配（AND）"
    if combines == {"OR"}:
        return "任一维度匹配即可（OR）"
    if combines == {"WEIGHTED"}:
        return "按权重加权合并（WEIGHTED）"
    if combines == {"LINEAR"}:
        return "按线性权重合并（LINEAR）"
    if combines == {"RRF"}:
        return "按倒数排名融合（RRF）"
    if combines:
        return "混合合并策略（" + " / ".join(sorted(combines)) + "）"
    return "默认合并策略"


def _build_overall(plan: "RetrievalPlan") -> OverallSummary:
    return OverallSummary(
        total_sub_queries=len(plan.sub_queries),
        max_depth=_compute_max_depth(plan),
        estimated_duration_ms=None,
        combine_summary=_combine_summary(plan),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_friendly_view(
    intent: "RetrievalIntent",
    plan: "RetrievalPlan",
) -> FriendlyRetrievalPlanView:
    """Assemble a fully-populated :class:`FriendlyRetrievalPlanView`.

    Never raises on a well-formed ``(intent, plan)`` pair.  Cards carry
    ``status="pending"`` because the builder runs pre-execution — the
    orchestrator can either overwrite ``result_summary`` post-run or
    ship an enrichment PR that mutates the view once results are in.
    """
    return FriendlyRetrievalPlanView(
        intent_summary=_build_intent_summary(intent),
        sub_query_cards=[
            _build_sub_query_card(sub, _display_index(idx + 1))
            for idx, sub in enumerate(plan.sub_queries)
        ],
        overall=_build_overall(plan),
    )
