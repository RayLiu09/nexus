"""Single source of truth for `friendly_view` Chinese display labels.

v1.3 R3-c mandates that Console rendering never derives Chinese labels
client-side.  Every `tag_type` / `domain` / `match_strategy` / `purpose` /
`channel` / `status` shown to the user must resolve through this module,
which keeps a *single* map from code to human-readable label per axis.

Design constraints:

1. **No silent fallback to the raw code.**  `get_*_display_label(...)` on an
   unknown code raises unless the caller explicitly opts into a fallback
   value.  Frontend that shows `job_demand` instead of `岗位需求` is a
   contract failure — surface it as a test failure, not as broken UX.
2. **Derive from existing constants where possible.**  `tag_taxonomy`
   already carries the Chinese `name` for each type; `DOMAIN_REGISTRY`
   already carries `display_name`.  We re-export both through helpers
   rather than duplicating the strings.
3. **Static coverage guarantees.**  ``test_display_labels.py`` verifies
   every enum value has a label, catching drift on future additions.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "CHANNEL_DISPLAY_LABELS",
    "PURPOSE_DISPLAY_LABELS",
    "MATCH_LAYER_DISPLAY_LABELS",
    "STATUS_DISPLAY_LABELS",
    "get_tag_type_display_label",
    "get_domain_display_label",
    "get_channel_display_label",
    "get_purpose_display_label",
    "get_match_layer_display_label",
    "get_status_display_label",
    "format_match_layer_summary",
    "format_match_strategy_display",
    "DisplayLabelError",
]


class DisplayLabelError(KeyError):
    """Raised when an unknown code is asked for its display label without
    an explicit fallback — signals a contract failure between backend and
    frontend."""


# ---------------------------------------------------------------------------
# tag_type — pulled from tag_taxonomy so a single source stays authoritative.
# ---------------------------------------------------------------------------


def _build_tag_type_map() -> dict[str, str]:
    from nexus_app.ai_governance.tag_taxonomy import TAG_TAXONOMY_V1_3

    return {t["code"]: t["name"] for t in TAG_TAXONOMY_V1_3["types"]}


def get_tag_type_display_label(code: str, *, fallback: str | None = None) -> str:
    """Return Chinese label for a `tag_taxonomy` code (e.g. 'region' → '地区')."""
    labels = _build_tag_type_map()
    if code in labels:
        return labels[code]
    if fallback is not None:
        return fallback
    raise DisplayLabelError(f"no display label for tag_type {code!r}")


# ---------------------------------------------------------------------------
# domain — pulled from DOMAIN_REGISTRY.display_name; keep helper for symmetry.
# ---------------------------------------------------------------------------


def get_domain_display_label(code: str, *, fallback: str | None = None) -> str:
    """Return Chinese label for a `BusinessDomain` code
    (e.g. 'job_demand' → '岗位需求')."""
    from nexus_app.retrieval.domain_registry import DOMAIN_REGISTRY
    from nexus_app.retrieval.schemas import BusinessDomain

    try:
        domain = BusinessDomain(code)
    except ValueError:
        if fallback is not None:
            return fallback
        raise DisplayLabelError(f"no display label for domain {code!r}") from None

    definition = DOMAIN_REGISTRY.get(domain)
    if definition is None:
        if fallback is not None:
            return fallback
        raise DisplayLabelError(f"domain {code!r} is unregistered")
    return definition.display_name


# ---------------------------------------------------------------------------
# channel — small enum, curated inline.
# ---------------------------------------------------------------------------


CHANNEL_DISPLAY_LABELS: dict[str, str] = {
    "structured": "结构化数据",
    "unstructured": "文档知识",
    "hybrid": "混合",
}


def get_channel_display_label(code: str, *, fallback: str | None = None) -> str:
    if code in CHANNEL_DISPLAY_LABELS:
        return CHANNEL_DISPLAY_LABELS[code]
    if fallback is not None:
        return fallback
    raise DisplayLabelError(f"no display label for channel {code!r}")


# ---------------------------------------------------------------------------
# purpose — v1.3 §5.3 subquery purpose codes, plus generic fallback.
# ---------------------------------------------------------------------------


PURPOSE_DISPLAY_LABELS: dict[str, str] = {
    "background_evidence": "背景依据",
    "trend_evidence": "趋势依据",
    "aggregation": "统计聚合",
    "ability_expansion": "能力扩展",
    "supply_side": "供给侧分析",
    "curriculum_support": "课程支撑",
    "supporting_evidence": "佐证依据",
    "source_lookup": "来源定位",
    "trend_aggregation": "趋势聚合",
    "planning_recommendation": "规划建议",
}


def get_purpose_display_label(code: str, *, fallback: str | None = None) -> str:
    if code in PURPOSE_DISPLAY_LABELS:
        return PURPOSE_DISPLAY_LABELS[code]
    if fallback is not None:
        return fallback
    # Silent tolerant fallback specifically for purpose because the code
    # vocabulary is open — we still emit a warning-worthy default rather
    # than raising.
    return code.replace("_", " ") if code else "（未标注目的）"


# ---------------------------------------------------------------------------
# match_layer — L1 / L1.5 / L4 → 中文短语.
# ---------------------------------------------------------------------------


MATCH_LAYER_DISPLAY_LABELS: dict[str, str] = {
    "L1": "精确匹配",
    "L1.5": "归一化匹配",
    "L2": "别名匹配",
    "L3": "编码匹配",
    "L4": "语义匹配",
    "L5": "全文兜底",
}


def get_match_layer_display_label(code: str, *, fallback: str | None = None) -> str:
    normalised = code.upper().replace("l", "L") if isinstance(code, str) else str(code)
    if normalised in MATCH_LAYER_DISPLAY_LABELS:
        return MATCH_LAYER_DISPLAY_LABELS[normalised]
    if fallback is not None:
        return fallback
    raise DisplayLabelError(f"no display label for match_layer {code!r}")


def format_match_layer_summary(distribution: dict[str, float]) -> str:
    """Turn ``{'L1': 0.6, 'L1.5': 0.25, 'L4': 0.15}`` into
    ``精确匹配 60% / 归一化匹配 25% / 语义匹配 15%``.

    Layers with 0 count are omitted so the summary stays terse.  Percentages
    are rounded to integers; the caller may pass ratios or absolute counts
    (they are normalised internally).
    """
    if not distribution:
        return ""
    total = sum(v for v in distribution.values() if v > 0)
    if total <= 0:
        return ""
    ordered = sorted(
        (item for item in distribution.items() if item[1] > 0),
        key=lambda kv: _match_layer_order(kv[0]),
    )
    parts = []
    for code, value in ordered:
        pct = round((value / total) * 100)
        if pct <= 0:
            continue
        label = get_match_layer_display_label(code, fallback=code)
        parts.append(f"{label} {pct}%")
    return " / ".join(parts)


def _match_layer_order(code: str) -> tuple[int, str]:
    """Sort order: L1 < L1.5 < L2 < L3 < L4 < L5."""
    ranks = {"L1": 10, "L1.5": 15, "L2": 20, "L3": 30, "L4": 40, "L5": 50}
    normalised = code.upper().replace("l", "L")
    return (ranks.get(normalised, 999), normalised)


def format_match_strategy_display(strategy: str) -> str:
    """Translate a raw `match_strategy` (e.g. ``"l1|l1.5|l4"``) into a
    human-readable phrase for card filter labels.

    Common phrases (curated):
    * ``l1``               → "精确匹配"
    * ``l1|l1.5``          → "精确匹配"（归一化不额外强调，用户视为同一档）
    * ``l1|l1.5|l4``       → "精确或语义匹配"
    * ``l4``               → "语义匹配"
    * anything else        → "精确或语义匹配"（保守兜底）
    """
    if not strategy:
        return "精确或语义匹配"
    layers = [
        piece.strip().upper().replace("L", "L")
        for piece in strategy.split("|")
        if piece.strip()
    ]
    layer_set = set(layers)
    if layer_set == {"L1"} or layer_set == {"L1", "L1.5"}:
        return "精确匹配"
    if layer_set == {"L4"}:
        return "语义匹配"
    if "L4" in layer_set:
        return "精确或语义匹配"
    return "精确匹配"


# ---------------------------------------------------------------------------
# status — SubQueryCard.status + orchestrator step status → 中文.
# ---------------------------------------------------------------------------


STATUS_DISPLAY_LABELS: dict[str, str] = {
    "pending": "等待执行",
    "running": "执行中",
    "completed": "已完成",
    "blocked": "等待前置节点完成",
    "degraded": "已完成（部分降级）",
    "failed": "失败",
    "skipped": "已跳过",
    "needs_clarification": "等待澄清",
}


def get_status_display_label(code: str, *, fallback: str | None = None) -> str:
    if code in STATUS_DISPLAY_LABELS:
        return STATUS_DISPLAY_LABELS[code]
    if fallback is not None:
        return fallback
    raise DisplayLabelError(f"no display label for status {code!r}")


# ---------------------------------------------------------------------------
# Debug snapshot — useful for one-shot introspection in scripts / notebooks.
# ---------------------------------------------------------------------------


def snapshot() -> dict[str, Any]:
    """Return all label maps in one dict for quick inspection.  Not used
    in the retrieval hot path; safe to call from scripts / tests."""
    return {
        "tag_types": _build_tag_type_map(),
        "domains": {
            code: get_domain_display_label(code)
            for code in ("course_textbook", "major_profile", "major_distribution",
                         "job_demand", "competency_analysis")
        },
        "channels": dict(CHANNEL_DISPLAY_LABELS),
        "purposes": dict(PURPOSE_DISPLAY_LABELS),
        "match_layers": dict(MATCH_LAYER_DISPLAY_LABELS),
        "statuses": dict(STATUS_DISPLAY_LABELS),
    }
