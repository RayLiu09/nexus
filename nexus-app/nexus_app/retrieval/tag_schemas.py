"""v1.3 tag_filter + friendly_view Pydantic contract (Sprint N.2 PR-2).

Kept out of ``schemas.py`` so the tag-side surface (cross_asset_tags /
tag_filters / binding_map / friendly_view) stays reviewable independently
of the pre-v1.3 retrieval plan shape.

Contract sources:

* v1.3 main design §5.1 (RetrievalIntent.cross_asset_tags),
  §5.3 (RetrievalSubQuery.tag_filters / binding_map / depends_on),
  §5.5 (RetrievalPlan.friendly_view).
* tag_filter_reliability_matrix_v1.md §3 invariants I-2 (single-source
  tag_type Literal) and I-5 (match layer ordering).

Design guarantees:

* Everything is a ``StrictModel`` subclass (``extra='forbid'``) so
  contract drift surfaces at schema-validate time rather than in a
  downstream matcher.
* Values that flow to the L1 exact-match path must be normalised by
  :func:`nexus_app.ai_governance.tag_normalization.normalize_tag_value`
  at the projection side.  This module carries the *type* contract, not
  the *value* contract.
* All new fields on ``RetrievalIntent`` / ``RetrievalSubQuery`` /
  ``RetrievalPlan`` (integrated in ``schemas.py``) default to safe empty
  values so pre-v1.3 payloads remain parseable — backwards read-compat
  is a hard requirement while M-B lands incrementally.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# Re-use the strict base defined next to the main schemas so the two
# files share ``extra='forbid'`` semantics.
from nexus_app.retrieval.schemas import StrictModel  # noqa: E402

__all__ = [
    # Literal type aliases
    "TagTypeCode",
    "TagBucketName",
    "MatchLayer",
    "CombineOp",
    "RERANK_COMBINE_OPS",
    "DEFAULT_RRF_K",
    "TAG_TYPE_CODES",
    "TAG_BUCKET_NAMES",
    # tag primitives
    "TagCandidate",
    "TimeRangeCandidate",
    "CrossAssetTags",
    "TagFilter",
    "BindingSpec",
    # friendly_view
    "ConfidenceLevel",
    "SubQueryStatus",
    "SubQueryAction",
    "EvidenceStrength",
    "DisplayConstraint",
    "IntentSummary",
    "DisplayFilter",
    "SubQueryResult",
    "SubQueryCard",
    "OverallSummary",
    "FriendlyRetrievalPlanView",
]


# ---------------------------------------------------------------------------
# Literal aliases — I-2 invariant (single source of taxonomy codes)
# ---------------------------------------------------------------------------


TagTypeCode = Literal[
    "region", "industry", "occupation", "major", "ability", "topic", "time_range"
]

TagBucketName = Literal[
    "regions", "industries", "occupations", "majors",
    "abilities", "topics", "time_ranges",
]

# Ordered tuple used by validators.  Keep synchronised with
# ``tag_taxonomy.TAG_TAXONOMY_V1_3.types[*].code`` and
# ``tag_payload.STRUCTURED_TAG_CATEGORY_CODES``.
TAG_TYPE_CODES: tuple[str, ...] = (
    "region", "industry", "occupation", "major", "ability", "topic", "time_range",
)
TAG_BUCKET_NAMES: tuple[str, ...] = (
    "regions", "industries", "occupations", "majors",
    "abilities", "topics", "time_ranges",
)


# match_layer names as displayed in warnings/result_summary.  Kept as a
# Literal so future additions land through code review.
MatchLayer = Literal["L1", "L1.5", "L2", "L3", "L4", "L5"]

CombineOp = Literal["AND", "OR", "WEIGHTED", "LINEAR", "RRF"]

# Ops that produce union set and drive rerank score aggregation.  Kept
# as a constant so tag_filter_execution / rerank / friendly_view stay in
# lock-step when a new op lands.
RERANK_COMBINE_OPS: frozenset[str] = frozenset({"WEIGHTED", "LINEAR", "RRF"})

# Reciprocal Rank Fusion — the k constant recommended by Cormack et al.
# (2009).  Overridable per-sub_query via ``RetrievalSubQuery.rrf_k``.
DEFAULT_RRF_K: int = 60


# ---------------------------------------------------------------------------
# Tag primitives — value carriers for cross_asset_tags / shared_constraints
# ---------------------------------------------------------------------------


class TagCandidate(StrictModel):
    """One free-form tag value + optional confidence.

    ``value`` is the human-readable form (e.g. ``"北京市"``).  Normalisation
    for the L1 exact-match column happens in the projection / matcher
    layers, not here — this schema carries the *type* contract only.
    """

    value: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("value")
    @classmethod
    def _strip_and_reject_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("tag value must not be empty after strip")
        return stripped


class TimeRangeCandidate(StrictModel):
    """Structured time_range candidate.  Mirrors ``tag_payload.TimeRangeValue``
    at the retrieval-side type layer."""

    kind: Literal["year_range", "point_in_time", "quarter", "half_year"] = "year_range"
    start: int | None = None
    end: int | None = None
    year: int | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_shape(self) -> "TimeRangeCandidate":
        if self.kind == "year_range":
            if self.start is None or self.end is None:
                raise ValueError(
                    "TimeRangeCandidate(kind='year_range') requires start and end"
                )
            if self.start > self.end:
                raise ValueError(
                    f"TimeRangeCandidate: start ({self.start}) must be <= end ({self.end})"
                )
        elif self.kind == "point_in_time":
            if self.year is None:
                raise ValueError(
                    "TimeRangeCandidate(kind='point_in_time') requires year"
                )
        return self


class CrossAssetTags(StrictModel):
    """The 7-bucket structured payload used by ``RetrievalIntent`` and
    ``RetrievalPlan.shared_constraints``.

    Bucket names use the plural form (``regions``, ``industries``, …) —
    the singular ``tag_type`` codes appear in ``tag_filters`` dict keys.
    See ``tag_payload.STRUCTURED_TAG_CATEGORIES`` for the canonical
    mapping.
    """

    regions: list[TagCandidate] = Field(default_factory=list)
    industries: list[TagCandidate] = Field(default_factory=list)
    occupations: list[TagCandidate] = Field(default_factory=list)
    majors: list[TagCandidate] = Field(default_factory=list)
    abilities: list[TagCandidate] = Field(default_factory=list)
    topics: list[TagCandidate] = Field(default_factory=list)
    time_ranges: list[TimeRangeCandidate] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return all(
            not getattr(self, bucket) for bucket in TAG_BUCKET_NAMES
        )


# ---------------------------------------------------------------------------
# TagFilter — sub_query-level filter spec (v1.3 §5.3)
# ---------------------------------------------------------------------------


class TagFilter(StrictModel):
    """One filter entry inside ``RetrievalSubQuery.tag_filters``.

    ``tags`` accepts either:
    * a static ``list[str]`` (planner writes explicit values), or
    * a single ``str`` **binding expression** like
      ``"$shared.industries"`` or ``"$q_job.output.top_jobs[*].job_title"``
      — resolved by the orchestrator at DAG execution time.

    ``match_strategy`` is a pipe-delimited layer expression (``"l1|l1.5|l4"``).
    Full parse rules live in ``TagAssetIndexResolver`` (PR-4); the schema
    guarantees only that the string is non-empty and contains valid
    layer codes.
    """

    tags: list[str] | str = Field(default_factory=list)
    match_strategy: str = Field(default="l1|l1.5|l4", min_length=1)
    semantic_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    top_k: int | None = Field(default=None, ge=1, le=1000)
    optional: bool = False

    @field_validator("match_strategy")
    @classmethod
    def _validate_match_strategy_tokens(cls, v: str) -> str:
        allowed = {"l1", "l1.5", "l2", "l3", "l4", "l5"}
        tokens = [t.strip().lower() for t in v.split("|")]
        if not tokens or any(not t for t in tokens):
            raise ValueError(f"match_strategy has empty layer token: {v!r}")
        unknown = [t for t in tokens if t not in allowed]
        if unknown:
            raise ValueError(
                f"match_strategy contains unknown layer(s) {unknown!r}; "
                f"allowed layers: {sorted(allowed)}"
            )
        return "|".join(tokens)  # canonicalise (lowercase)

    @field_validator("tags")
    @classmethod
    def _validate_tags_binding_or_list(
        cls, v: list[str] | str,
    ) -> list[str] | str:
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                raise ValueError("binding expression must not be empty")
            if not stripped.startswith("$"):
                raise ValueError(
                    "binding expression must start with '$' "
                    "(e.g. '$shared.industries' or "
                    "'$q_job.output.top_jobs[*].job_title')"
                )
            return stripped
        if not isinstance(v, list):
            raise TypeError(
                "tags must be list[str] or a binding expression str"
            )
        cleaned: list[str] = []
        for item in v:
            if not isinstance(item, str):
                raise TypeError("each tag entry must be a str")
            stripped = item.strip()
            if not stripped:
                raise ValueError("tag values must be non-empty after strip")
            cleaned.append(stripped)
        return cleaned


# ---------------------------------------------------------------------------
# BindingSpec — upstream-output → downstream-candidate binding
# ---------------------------------------------------------------------------


class BindingSpec(StrictModel):
    """One entry in ``RetrievalSubQuery.binding_map``.

    ``source`` is a path expression (v1.3 §5.3) into an upstream
    sub_query's declared ``output_binding``, e.g.
    ``"$q_job.output.top_jobs[*].job_title"``.  The path resolver lives in
    the orchestrator (PR-11); the schema enforces only structural
    integrity.
    """

    source: str = Field(min_length=1)
    as_tag_type: TagTypeCode
    match_strategy: str = Field(default="l1|l1.5|l4", min_length=1)
    semantic_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    limit: int | None = Field(default=None, ge=1, le=100)

    @field_validator("source")
    @classmethod
    def _source_starts_with_dollar_qid(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped.startswith("$"):
            raise ValueError(
                "binding source must start with '$' "
                "(e.g. '$q_job.output.top_jobs[*].job_title')"
            )
        # Require at least "$<qid>." to avoid meaningless '$' bindings.
        if "." not in stripped[1:]:
            raise ValueError(
                "binding source must reference a sub_query field "
                "(e.g. '$q_id.output.<field>')"
            )
        return stripped

    @field_validator("match_strategy")
    @classmethod
    def _validate_match_strategy_tokens(cls, v: str) -> str:
        # Reuse TagFilter's logic by delegating.
        return TagFilter._validate_match_strategy_tokens.__func__(cls, v)


# ---------------------------------------------------------------------------
# friendly_view — Console single-conversation-stream contract (v1.3 §5.5)
# ---------------------------------------------------------------------------


ConfidenceLevel = Literal["high", "medium", "low"]

SubQueryStatus = Literal[
    "pending", "running", "completed", "blocked",
    "degraded", "failed", "skipped",
]

SubQueryAction = Literal[
    "rerun", "cancel", "skip", "view_details", "view_raw",
]

EvidenceStrength = Literal["strong", "medium", "weak"]


class DisplayConstraint(StrictModel):
    """Chinese-labelled cross_asset_tag surfaced in the intent card."""

    label: str = Field(min_length=1)      # e.g. "地区"
    value: str = Field(min_length=1)      # e.g. "北京市"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_display: str = Field(min_length=1)  # e.g. "从问题中识别"


class IntentSummary(StrictModel):
    natural_language: str = Field(min_length=1)
    business_domains_display: list[str] = Field(default_factory=list)
    identified_constraints: list[DisplayConstraint] = Field(default_factory=list)
    unresolved_terms: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel
    clarification_suggestions: list[str] = Field(default_factory=list)


class DisplayFilter(StrictModel):
    """One filter chip surfaced on a sub_query card."""

    label: str = Field(min_length=1)      # e.g. "地区"
    values: list[str] = Field(default_factory=list)
    match_strategy_display: str = Field(min_length=1)  # e.g. "精确匹配"
    is_optional: bool = False
    is_from_binding: bool | None = None
    binding_source_display: str | None = None


class SubQueryResult(StrictModel):
    """Post-execution result summary displayed on a completed card."""

    hit_count: int = Field(ge=0)
    hit_count_display: str = Field(min_length=1)   # e.g. "156 条记录"
    duration_ms: int = Field(ge=0)
    duration_display: str = Field(min_length=1)    # e.g. "620 ms"
    match_layer_summary: str = ""                   # allowed to be empty on no-hit
    evidence_strength: EvidenceStrength
    evidence_strength_display: str = Field(min_length=1)  # e.g. "证据强度：强"
    warnings: list[str] = Field(default_factory=list)


class SubQueryCard(StrictModel):
    query_id: str = Field(min_length=1)
    display_index: str = Field(min_length=1)   # e.g. "②"
    title: str = Field(min_length=1)
    purpose_display: str = Field(min_length=1)
    channel_display: str = Field(min_length=1)
    domain_display: str = Field(min_length=1)
    depends_on_display: list[str] = Field(default_factory=list)
    filter_summary: list[DisplayFilter] = Field(default_factory=list)
    status: SubQueryStatus
    status_display: str = Field(min_length=1)
    degraded_reasons: list[str] = Field(default_factory=list)
    result_summary: SubQueryResult | None = None
    actions_available: list[SubQueryAction] = Field(default_factory=list)


class OverallSummary(StrictModel):
    total_sub_queries: int = Field(ge=0)
    max_depth: int = Field(ge=0)
    estimated_duration_ms: int | None = Field(default=None, ge=0)
    combine_summary: str = Field(min_length=1)     # e.g. "所有维度均需匹配（AND）"


class FriendlyRetrievalPlanView(StrictModel):
    """Console single-conversation-stream payload — v1.3 R3-c contract.

    Generated by the orchestrator; consumed verbatim by
    ``SearchPlayground`` / ``ConversationStream``.  No client-side
    derivation (Chinese labels sourced from
    ``retrieval.display_labels``).
    """

    intent_summary: IntentSummary
    sub_query_cards: list[SubQueryCard] = Field(default_factory=list)
    overall: OverallSummary


# ---------------------------------------------------------------------------
# ConfigDict re-export for downstream Sprint N.2 sub-schemas
# ---------------------------------------------------------------------------


# Kept for potential re-use by PR-4 Resolver return types (out of scope
# for this PR).
_STRICT_CONFIG: ConfigDict = ConfigDict(extra="forbid", use_enum_values=True)
