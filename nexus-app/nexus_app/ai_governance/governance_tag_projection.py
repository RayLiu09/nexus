"""Governance-side tag projection — v1.3 §16 PR-8.

Writes ``tag_asset_index`` rows with ``source=governance_tag`` from the
StructuredTagBag emitted by ``_TAGGING_PROMPT_V2`` (see
``docs/knowledge_retrieval_result_enhancement_v1.3.md §16.4``).

Contract:

* Every LLM-produced tag carries ``value``, ``confidence``, and
  ``evidence_span`` (per bucket).  Only tags at or above
  ``confidence_threshold`` are projected — sub-threshold tags stay on
  ``ai_governance_run.raw_output`` for human review and don't land in
  the semantic bridge.
* All rows target ``NORMALIZED_ASSET_REF`` (governance tagging runs at
  the source-asset level; it does not fan out to child records).
* Idempotency (I-10) is enforced at the ``(target_type, target_id,
  source)`` triple — re-running the tagging profile atomically
  supersedes the prior run.
* ``extraction_run_id`` is set on every row so audit / recompute can
  correlate tags to their producing ``ai_governance_run``.

Bucket → tag_type mapping matches the projection engine's convention
(plural → singular).  ``time_ranges`` uses ``time_range`` and expects
either an inline ``start`` / ``end`` / ``year`` triple or a raw
``value`` string that ``_TIME_TAG_TYPES`` will normalise.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping

from nexus_app.ai_governance.tag_projection import (
    TagRowPayload,
    persist_tag_rows,
)
from nexus_app.ai_governance.tag_normalization import normalize_tag_value
from nexus_app.enums import TagAssetIndexSource, TagAssetIndexTargetType

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


__all__ = [
    "GovernanceTagProjectionResult",
    "project_governance_tag_bag",
    "BUCKET_TO_TAG_TYPE",
]


# ``StructuredTagBag`` bucket names → singular tag_type codes.  Kept
# in-module to avoid cross-package coupling; identical to the mapping in
# ``retrieval.tag_resolver`` but sourced independently so a schema change
# on either side is visible in code review.
BUCKET_TO_TAG_TYPE: dict[str, str] = {
    "regions": "region",
    "industries": "industry",
    "occupations": "occupation",
    "majors": "major",
    "abilities": "ability",
    "topics": "topic",
    "time_ranges": "time_range",
}


@dataclass(frozen=True)
class GovernanceTagProjectionResult:
    """Summary emitted by :func:`project_governance_tag_bag`.

    ``rows_persisted`` matches the count of rows actually written to
    ``tag_asset_index`` — sub-threshold tags don't count.  ``dropped_below_threshold``
    reports how many tags were skipped due to low confidence so the
    caller can populate an audit / review-queue entry.
    """

    rows_persisted: int
    tag_count_examined: int
    dropped_below_threshold: int
    dropped_malformed: int
    dropped_buckets: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def project_governance_tag_bag(
    session: "Session",
    *,
    normalized_ref_id: str,
    asset_version_id: str,
    tag_bag: Mapping[str, Any],
    extraction_run_id: str,
    confidence_threshold: float,
    trace_id: str | None = None,
) -> GovernanceTagProjectionResult:
    """Project ``StructuredTagBag`` output to ``tag_asset_index`` rows.

    Parameters
    ----------
    session:
        Active caller-owned SQLAlchemy Session (not committed).
    normalized_ref_id:
        ``NormalizedAssetRef.id`` — becomes ``target_id`` for every row.
    asset_version_id:
        Parent asset_version.id (cheap cache-invalidation column).
    tag_bag:
        The 7-bucket dict emitted by the tagging LLM.  Structural
        deviations (missing bucket, non-list entry, non-dict tag) are
        silently dropped — the caller inspects ``dropped_malformed`` to
        judge severity.
    extraction_run_id:
        ``ai_governance_run.id`` correlating produced rows back to the
        run.  Not used for idempotency (that's the triple), but stored
        so audits can trace tags to their producing run.
    confidence_threshold:
        Rows below this threshold stay off the semantic bridge.  Pass
        ``0.0`` to disable the filter (useful for tests + recompute
        scenarios that already vetted quality upstream).
    """
    payloads: list[TagRowPayload] = []
    tag_count_examined = 0
    dropped_below_threshold = 0
    dropped_malformed = 0
    dropped_buckets: list[str] = []

    # Deduplicate per (tag_type, normalised_value) — LLM output can
    # legitimately repeat the same value across buckets or emit duplicate
    # entries within a bucket.  First-emission wins so the bucket order
    # is preserved for observability.
    seen: set[tuple[str, str]] = set()

    for bucket_name, tag_type in BUCKET_TO_TAG_TYPE.items():
        entries = tag_bag.get(bucket_name)
        if entries is None:
            continue
        if not isinstance(entries, list):
            dropped_buckets.append(f"{bucket_name}:not_a_list")
            continue

        for entry in entries:
            tag_count_examined += 1
            tag = _coerce_tag_entry(entry, tag_type)
            if tag is None:
                dropped_malformed += 1
                continue
            value, confidence, evidence_span = tag
            if confidence is not None and confidence < confidence_threshold:
                dropped_below_threshold += 1
                continue
            normalised = normalize_tag_value(value, tag_type)
            if not normalised:
                dropped_malformed += 1
                continue
            key = (tag_type, normalised)
            if key in seen:
                continue
            seen.add(key)
            payloads.append(
                TagRowPayload(
                    tag_type=tag_type,
                    tag_value=value,
                    tag_value_normalized=normalised,
                    target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
                    target_id=normalized_ref_id,
                    asset_version_id=asset_version_id,
                    source=TagAssetIndexSource.GOVERNANCE_TAG,
                    confidence=confidence,
                    extraction_run_id=extraction_run_id,
                    trace_id=trace_id,
                    evidence_span=evidence_span,
                )
            )

    rows_persisted = persist_tag_rows(
        session, payloads,
        target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
        target_id=normalized_ref_id,
        source=TagAssetIndexSource.GOVERNANCE_TAG,
    )

    return GovernanceTagProjectionResult(
        rows_persisted=rows_persisted,
        tag_count_examined=tag_count_examined,
        dropped_below_threshold=dropped_below_threshold,
        dropped_malformed=dropped_malformed,
        dropped_buckets=dropped_buckets,
    )


# ---------------------------------------------------------------------------
# Entry coercion
# ---------------------------------------------------------------------------


def _coerce_tag_entry(
    entry: Any,
    tag_type: str,
) -> tuple[str, float | None, str | None] | None:
    """Extract ``(value, confidence, evidence_span)`` from an LLM tag entry.

    Handles the three shapes ``_TAGGING_PROMPT_V2`` emits:

    * ``{"value": "...", "confidence": 0.9, "evidence_span": "..."}``
      — normal case for the six regular buckets.
    * ``{"kind": "year_range", "start": 2020, "end": 2024,
       "confidence": ..., "evidence_span": ...}`` — time_range bucket.
    * A bare ``str`` — surfaces for buckets where the LLM decided
      confidence carriage wasn't needed (rare, but supported).
    """
    if isinstance(entry, str):
        stripped = entry.strip()
        if not stripped:
            return None
        return (stripped, None, None)

    if not isinstance(entry, Mapping):
        return None

    if tag_type == "time_range":
        # Prefer explicit start/end/year triple; fall back to `value`
        # string when the LLM provided one.
        value = _time_range_display(entry)
        if not value:
            return None
    else:
        raw_value = entry.get("value") or entry.get("code") or entry.get("tag")
        if not isinstance(raw_value, str):
            return None
        value = raw_value.strip()
        if not value:
            return None

    confidence: float | None = None
    raw_conf = entry.get("confidence")
    if isinstance(raw_conf, (int, float)):
        confidence = float(raw_conf)

    evidence_span: str | None = None
    raw_evidence = entry.get("evidence_span")
    if isinstance(raw_evidence, str):
        stripped_evidence = raw_evidence.strip()
        if stripped_evidence:
            evidence_span = stripped_evidence

    return (value, confidence, evidence_span)


def _time_range_display(entry: Mapping[str, Any]) -> str | None:
    """Render a time_range candidate as a display string for L1 lookup.

    Preserves the LLM's ``value`` if it provided one; otherwise builds
    a ``"YYYY-YYYY"`` / ``"YYYY"`` string from ``start`` / ``end`` /
    ``year``.  Callers rely on the projection engine's
    ``normalize_tag_value`` to canonicalise this further.
    """
    explicit = entry.get("value")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    kind = entry.get("kind")
    start = entry.get("start")
    end = entry.get("end")
    year = entry.get("year")

    if kind == "year_range" and isinstance(start, int) and isinstance(end, int):
        return f"{start}-{end}"
    if kind == "point_in_time" and isinstance(year, int):
        return str(year)
    if isinstance(year, int):
        return str(year)
    if isinstance(start, int) and isinstance(end, int):
        return f"{start}-{end}"
    return None
