"""Dual-shape reader for ``governance_result.tags``.

v1.3 introduces a structured 7-category tag payload
(see ``docs/knowledge_retrieval_result_enhancement_v1.3.md`` §4.1) that will
replace the pre-v1.3 flat ``list[str]`` shape.  Both shapes must coexist
during the rollout window:

* **Legacy flat** — ``["直播电商", "北京市", "L2"]`` written by
  ``_extract_governance_tags`` in :mod:`nexus_app.governance.decision_service`.
* **Structured** — one bucket per ``tag_taxonomy.types[*].code`` (regions,
  industries, occupations, majors, abilities, topics, time_ranges), each
  containing a list of ``TagValue`` objects.

A2 delivers the *read* side only.  Writing the new shape is deferred to A3
(tagging prompt profile v2 upgrade) so that a mid-rollout mixed corpus
doesn't require a coordinated schema flip.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "STRUCTURED_TAG_CATEGORY_CODES",
    "STRUCTURED_TAG_CATEGORIES",
    "TagValue",
    "TimeRangeValue",
    "StructuredTagBag",
    "TagShape",
    "detect_tags_shape",
    "normalize_to_structured",
    "flatten_to_legacy",
    "empty_structured_tag_bag",
]


# Keep this list synchronised with the ``code`` values in
# ``nexus_app.ai_governance.tag_taxonomy.TAG_TAXONOMY_V1_3["types"]``.
STRUCTURED_TAG_CATEGORY_CODES: tuple[str, ...] = (
    "regions",
    "industries",
    "occupations",
    "majors",
    "abilities",
    "topics",
    "time_ranges",
)


# tag_taxonomy uses singular type codes (region / industry / …); the
# structured payload uses plural bucket names (regions / industries / …).
# This mapping is authoritative for both directions.
STRUCTURED_TAG_CATEGORIES: dict[str, str] = {
    "region": "regions",
    "industry": "industries",
    "occupation": "occupations",
    "major": "majors",
    "ability": "abilities",
    "topic": "topics",
    "time_range": "time_ranges",
}


TagShape = Literal["flat", "structured", "empty", "unknown"]


class TagValue(BaseModel):
    """A single business tag with confidence and evidence.

    ``confidence`` and ``evidence_span`` are ``None`` for legacy tags that
    were up-cast from flat strings; new tagging profile v2 populates both.
    """

    value: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_span: str | None = None

    model_config = ConfigDict(extra="ignore")


class TimeRangeValue(BaseModel):
    """Structured time_range payload — v1.3 §4.1.

    Distinct from ``TagValue`` because time expresses a range or a point,
    not a free-form string; encoding it as a string would lose the
    machine-comparable semantics needed by structured time filters
    (``$shared.time_ranges``) in DAG binding.

    Two supported shapes:
    * ``kind="year_range"`` with ``start`` + ``end`` — inclusive year span.
    * ``kind="point_in_time"`` with ``year`` — single year.

    Extra kinds (quarter / half_year) are accepted at the schema level
    but do not yet drive filter semantics; adding a new kind should also
    update the resolver.
    """

    kind: Literal["year_range", "point_in_time", "quarter", "half_year"] = "year_range"
    start: int | None = None
    end: int | None = None
    year: int | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_span: str | None = None

    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="after")
    def _validate_shape(self) -> "TimeRangeValue":
        if self.kind == "year_range":
            if self.start is None or self.end is None:
                raise ValueError(
                    "TimeRangeValue(kind='year_range') requires both start and end"
                )
            if self.start > self.end:
                raise ValueError(
                    f"TimeRangeValue: start ({self.start}) must be <= end ({self.end})"
                )
        elif self.kind == "point_in_time":
            if self.year is None:
                raise ValueError(
                    "TimeRangeValue(kind='point_in_time') requires year"
                )
        return self

    def to_display_string(self) -> str:
        """Terse human-readable form used when the payload is flattened
        back into a ``list[str]`` for legacy consumers."""
        if self.kind == "year_range" and self.start is not None and self.end is not None:
            if self.start == self.end:
                return str(self.start)
            return f"{self.start}-{self.end}"
        if self.kind == "point_in_time" and self.year is not None:
            return str(self.year)
        return self.kind

    def dedup_key(self) -> tuple:
        """Stable tuple used for duplicate detection inside a bag."""
        return (self.kind, self.start, self.end, self.year)


class StructuredTagBag(BaseModel):
    """The v1.3 §4.1 structured payload — one bucket per taxonomy type.

    ``time_ranges`` uses ``TimeRangeValue`` instead of ``TagValue`` because
    time carries range/point semantics that structured filters compare
    numerically; free-form string encoding would defeat that.
    """

    regions: list[TagValue] = Field(default_factory=list)
    industries: list[TagValue] = Field(default_factory=list)
    occupations: list[TagValue] = Field(default_factory=list)
    majors: list[TagValue] = Field(default_factory=list)
    abilities: list[TagValue] = Field(default_factory=list)
    topics: list[TagValue] = Field(default_factory=list)
    time_ranges: list[TimeRangeValue] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="after")
    def _no_duplicate_values_within_category(self) -> "StructuredTagBag":
        """Guard against redundant AI extraction — one value per category.

        ``time_ranges`` is de-duplicated by structural key (kind/start/end/year)
        rather than string value because it does not carry a ``value`` field.
        """
        for cat in STRUCTURED_TAG_CATEGORY_CODES:
            items = getattr(self, cat)
            if cat == "time_ranges":
                keys = [t.dedup_key() for t in items]
            else:
                keys = [t.value for t in items]
            if len(keys) != len(set(keys)):
                raise ValueError(
                    f"structured_tag_bag: duplicate entries in category '{cat}'"
                )
        return self


def empty_structured_tag_bag() -> StructuredTagBag:
    """Factory for an empty bag with all 7 buckets present."""
    return StructuredTagBag()


def detect_tags_shape(raw: Any) -> TagShape:
    """Classify a ``governance_result.tags`` payload without validating it.

    ``[]``            → ``"empty"``
    ``list[str]``     → ``"flat"``
    ``dict`` with any known bucket key → ``"structured"``
    anything else     → ``"unknown"``
    """
    if raw is None:
        return "empty"
    if isinstance(raw, list):
        if not raw:
            return "empty"
        if all(isinstance(v, str) for v in raw):
            return "flat"
        return "unknown"
    if isinstance(raw, dict):
        if not raw:
            return "empty"
        if any(key in raw for key in STRUCTURED_TAG_CATEGORY_CODES):
            return "structured"
        return "unknown"
    return "unknown"


def normalize_to_structured(raw: Any) -> StructuredTagBag:
    """Coerce any recognised tags payload into a ``StructuredTagBag``.

    Legacy flat strings land in ``topics`` with ``confidence=None`` and
    ``evidence_span=None``.  This is the safe default for the rollout
    window — the ``recompute.recompute_tagging_only`` path (A3) is what
    eventually rewrites these rows with a real taxonomy category.

    An empty or ``None`` payload returns an empty bag (no buckets are
    dropped, so downstream consumers can rely on all 7 buckets existing).
    """
    shape = detect_tags_shape(raw)
    if shape == "empty":
        return empty_structured_tag_bag()
    if shape == "flat":
        # Deduplicate while preserving order.
        seen: set[str] = set()
        topics: list[TagValue] = []
        for value in raw:
            if not isinstance(value, str):
                continue
            v = value.strip()
            if not v or v in seen:
                continue
            seen.add(v)
            topics.append(TagValue(value=v))
        return StructuredTagBag(topics=topics)
    if shape == "structured":
        return StructuredTagBag.model_validate(raw)
    raise ValueError(
        f"unrecognised governance_result.tags shape: {type(raw).__name__}"
    )


def flatten_to_legacy(bag: StructuredTagBag | dict[str, Any] | list[Any]) -> list[str]:
    """Flatten any recognised payload back into the pre-v1.3 ``list[str]``.

    Legacy consumers (still relying on the flat shape) can call this to
    stay compatible during rollout.  Order: iterate buckets in the
    canonical ``STRUCTURED_TAG_CATEGORY_CODES`` order, preserving each
    bucket's internal order and de-duplicating across the whole bag.

    Dict input is traversed **tolerantly** — malformed items (empty value,
    missing key, wrong type) are silently skipped rather than raising.
    This matters when a raw LLM tagging payload is flattened as part of
    ``decision_service._extract_governance_tags``: the caller's own
    validation filter runs afterwards and should not be short-circuited
    by a schema violation on a single garbage bucket entry.
    """
    if isinstance(bag, list):
        # Already flat; still de-duplicate to be safe.
        seen: set[str] = set()
        result: list[str] = []
        for v in bag:
            if isinstance(v, str) and v not in seen:
                seen.add(v)
                result.append(v)
        return result

    if isinstance(bag, StructuredTagBag):
        seen = set()
        result = []
        for cat in STRUCTURED_TAG_CATEGORY_CODES:
            for tv in getattr(bag, cat):
                if cat == "time_ranges":
                    # TimeRangeValue has no ``.value`` — render its
                    # human-readable form so legacy consumers still see it.
                    text = tv.to_display_string()
                else:
                    text = tv.value
                if text and text not in seen:
                    seen.add(text)
                    result.append(text)
        return result

    if isinstance(bag, dict):
        seen = set()
        result = []
        for cat in STRUCTURED_TAG_CATEGORY_CODES:
            bucket = bag.get(cat)
            if not isinstance(bucket, list):
                continue
            for item in bucket:
                value: Any
                if isinstance(item, dict):
                    value = item.get("value")
                elif isinstance(item, str):
                    value = item
                else:
                    continue
                if not isinstance(value, str):
                    continue
                cleaned = value.strip()
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    result.append(cleaned)
        return result

    return []
