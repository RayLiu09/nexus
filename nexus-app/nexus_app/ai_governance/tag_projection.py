"""Projection engine — v1.3 §2.4 PR-6 skeleton.

Pure function that maps a **structured record dict** (or an outline node
dict) to a list of ``TagAssetIndex`` payload rows per
``PROJECTION_WHITELIST_V1_3``.  The engine is intentionally deterministic
and side-effect free:

* The caller (Pipeline B writer, outline generator, governance投影 job)
  is responsible for persistence.
* Every ``tag_value`` runs through
  :func:`nexus_app.ai_governance.tag_normalization.normalize_tag_value` —
  this is the projection side of the I-1 invariant.
* Time-range projections synthesise a ``TimeRangeValue`` for the
  ``time_range`` bucket (``StructuredTagBag.time_ranges`` shape).
* Long-text fields declared in the whitelist are **never** projected.
* Conditional projections (``item_type='professional_skill'`` on the
  requirement item table) are gated at the engine boundary.

The persistence helper ``persist_tag_rows`` implements the I-10
invariant: **projecting the same record twice yields the same set of
rows** (delete-then-insert per ``(target_type, target_id, source)``
triple).  Callers that guarantee idempotency at a higher layer may skip
the helper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping

from sqlalchemy import delete
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.projection_config import (
    PROJECTION_WHITELIST_V1_3,
    get_conditional_projections,
    get_field_projections,
    get_long_text_fields,
    get_metadata_projections,
)
from nexus_app.ai_governance.tag_normalization import (
    TagTypeCode,
    normalize_tag_value,
)
from nexus_app.enums import TagAssetIndexSource, TagAssetIndexTargetType

__all__ = [
    "TagRowPayload",
    "project_field_projections",
    "project_conditional_projections",
    "project_metadata_projections",
    "project_record_to_tag_rows",
    "persist_tag_rows",
]


# Mapping from the whitelist table names to the DB-enum target_type
# values.  Table names in the whitelist match SQLAlchemy ``__tablename__``
# so this table doubles as a coverage assertion (see tests).
_TABLE_TO_TARGET_TYPE: dict[str, TagAssetIndexTargetType] = {
    "job_demand_record": TagAssetIndexTargetType.JOB_DEMAND_RECORD,
    "job_demand_requirement_item": TagAssetIndexTargetType.JOB_DEMAND_REQUIREMENT_ITEM,
    "major_distribution_record": TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
    "occupational_ability_item": TagAssetIndexTargetType.OCCUPATIONAL_ABILITY_ITEM,
    "major_profile_ability": TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
    "knowledge_outline_node": TagAssetIndexTargetType.OUTLINE_NODE,
    "task_outline_node": TagAssetIndexTargetType.OUTLINE_NODE,
}


# The set of tag_type codes that carry structured range semantics rather
# than a free-form string value.
_TIME_TAG_TYPES: frozenset[TagTypeCode] = frozenset({"time_range"})


@dataclass(frozen=True)
class TagRowPayload:
    """Pure-data payload for one prospective ``TagAssetIndex`` row.

    Immutability keeps the engine's output safe to reuse (e.g. cached
    projection rerun during a writer retry).  ``created_at`` / ``id`` are
    filled in by the ORM at persistence time.

    ``evidence_span`` (v1.3 PR-8) carries the LLM-produced snippet from
    the source document; NULL for field/outline/expert_manual sources.
    """

    tag_type: str
    tag_value: str
    tag_value_normalized: str
    target_type: TagAssetIndexTargetType
    target_id: str
    asset_version_id: str
    source: TagAssetIndexSource
    standard_code: str | None = None
    confidence: float | None = None
    extraction_run_id: str | None = None
    trace_id: str | None = None
    evidence_span: str | None = None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def _stringify(value: Any) -> str:
    """Common stringification with time-aware handling: ``date`` /
    ``datetime`` become an ISO date, ints become str, everything else via
    ``str``."""
    if isinstance(value, (datetime, date)):
        # date subclasses datetime — call isoformat on the more specific
        # class first.
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    return str(value)


def _extract_year(value: Any) -> int | None:
    """Best-effort year extraction for ``time_range`` projections."""
    if isinstance(value, datetime):
        return value.year
    if isinstance(value, date):
        return value.year
    if isinstance(value, int):
        return value if 1900 <= value <= 2100 else None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit() and len(stripped) == 4:
            year = int(stripped)
            return year if 1900 <= year <= 2100 else None
    return None


def _emit_payloads_from_value(
    *,
    raw_value: Any,
    tag_types: Iterable[str],
    target_type: TagAssetIndexTargetType,
    target_id: str,
    asset_version_id: str,
    source: TagAssetIndexSource,
    confidence: float | None,
    extraction_run_id: str | None,
    trace_id: str | None,
    evidence_span: str | None = None,
) -> list[TagRowPayload]:
    """Emit one ``TagRowPayload`` per (tag_type × normalised value)."""
    if raw_value is None:
        return []

    display_value = _stringify(raw_value).strip()
    if not display_value:
        return []

    payloads: list[TagRowPayload] = []
    for tag_type in tag_types:
        if tag_type in _TIME_TAG_TYPES:
            year = _extract_year(raw_value)
            if year is None:
                # Fall back to the raw string representation for L1
                # exact match; L4 semantic search remains available.
                normalised = normalize_tag_value(display_value, tag_type)
                if not normalised:
                    continue
                payloads.append(
                    TagRowPayload(
                        tag_type=tag_type,
                        tag_value=display_value,
                        tag_value_normalized=normalised,
                        target_type=target_type,
                        target_id=target_id,
                        asset_version_id=asset_version_id,
                        source=source,
                        confidence=confidence,
                        extraction_run_id=extraction_run_id,
                        trace_id=trace_id,
                        evidence_span=evidence_span,
                    )
                )
            else:
                # Canonical year string; L1 lookups become trivial.
                year_str = str(year)
                payloads.append(
                    TagRowPayload(
                        tag_type=tag_type,
                        tag_value=year_str,
                        tag_value_normalized=year_str,
                        target_type=target_type,
                        target_id=target_id,
                        asset_version_id=asset_version_id,
                        source=source,
                        confidence=confidence,
                        extraction_run_id=extraction_run_id,
                        trace_id=trace_id,
                        evidence_span=evidence_span,
                    )
                )
            continue

        normalised = normalize_tag_value(display_value, tag_type)
        if not normalised:
            continue
        payloads.append(
            TagRowPayload(
                tag_type=tag_type,
                tag_value=display_value,
                tag_value_normalized=normalised,
                target_type=target_type,
                target_id=target_id,
                asset_version_id=asset_version_id,
                source=source,
                confidence=confidence,
                extraction_run_id=extraction_run_id,
                trace_id=trace_id,
                evidence_span=evidence_span,
            )
        )
    return payloads


def project_field_projections(
    *,
    table_name: str,
    record: Mapping[str, Any],
    target_type: TagAssetIndexTargetType,
    target_id: str,
    asset_version_id: str,
    source: TagAssetIndexSource,
    trace_id: str | None = None,
) -> list[TagRowPayload]:
    """Emit rows for the ``field_projections`` section of the whitelist."""
    payloads: list[TagRowPayload] = []
    long_text_fields = set(get_long_text_fields(table_name))
    for field_name, tag_types in get_field_projections(table_name).items():
        if field_name in long_text_fields:
            # Whitelist misconfiguration guard — declaring the same
            # column in both buckets would silently emit noise.
            continue
        payloads.extend(
            _emit_payloads_from_value(
                raw_value=record.get(field_name),
                tag_types=tag_types,
                target_type=target_type,
                target_id=target_id,
                asset_version_id=asset_version_id,
                source=source,
                confidence=None,  # field projections have no LLM confidence
                extraction_run_id=None,
                trace_id=trace_id,
            )
        )
    return payloads


def _matches_condition(record: Mapping[str, Any], when: Mapping[str, Any]) -> bool:
    """All ``when`` key/value pairs must match the record."""
    for key, expected in when.items():
        if record.get(key) != expected:
            return False
    return True


def _pick_conditional_value(
    record: Mapping[str, Any],
    value_field: Iterable[str],
) -> Any | None:
    """Iterate the declared value-source fields in order; return the first
    non-empty match."""
    for candidate in value_field:
        raw = record.get(candidate)
        if raw is None:
            continue
        text = _stringify(raw).strip()
        if text:
            return raw
    return None


def _resolve_dotted_path(
    record: Mapping[str, Any],
    dotted_path: str,
) -> Any:
    """Walk a ``"a.b.c"`` dotted path over a nested mapping.

    Returns ``None`` when any intermediate segment is missing or is not
    a mapping.  The terminal value may be any type; the caller decides
    whether to iterate it (list-of-strings) or scalar-normalise it.
    Kept intentionally strict — deep JSON schemas like
    ``node_metadata.keywords`` are declared explicitly in the whitelist,
    so unexpected shapes should surface as "no projection rows", not
    silently bulldoze through mismatched types.
    """
    segments = dotted_path.split(".")
    current: Any = record
    for segment in segments:
        if isinstance(current, Mapping) and segment in current:
            current = current[segment]
        else:
            return None
    return current


def project_metadata_projections(
    *,
    table_name: str,
    record: Mapping[str, Any],
    target_type: TagAssetIndexTargetType,
    target_id: str,
    asset_version_id: str,
    source: TagAssetIndexSource,
    trace_id: str | None = None,
) -> list[TagRowPayload]:
    """Emit rows for the ``metadata_projections`` section of the whitelist.

    v1.3 PR-8 addition — walks dotted paths into JSON columns.  When
    the resolved value is a list, each element becomes an independent
    projection (deduplicated at the top-level engine).  When it's a
    single scalar, one row is emitted.  Any other shape (nested dict,
    non-string element) is silently dropped by the value normaliser.
    """
    payloads: list[TagRowPayload] = []
    for dotted_path, tag_types in get_metadata_projections(table_name).items():
        resolved = _resolve_dotted_path(record, dotted_path)
        if resolved is None:
            continue
        values = resolved if isinstance(resolved, (list, tuple)) else [resolved]
        for value in values:
            payloads.extend(
                _emit_payloads_from_value(
                    raw_value=value,
                    tag_types=tag_types,
                    target_type=target_type,
                    target_id=target_id,
                    asset_version_id=asset_version_id,
                    source=source,
                    confidence=None,
                    extraction_run_id=None,
                    trace_id=trace_id,
                )
            )
    return payloads


def project_conditional_projections(
    *,
    table_name: str,
    record: Mapping[str, Any],
    target_type: TagAssetIndexTargetType,
    target_id: str,
    asset_version_id: str,
    source: TagAssetIndexSource,
    trace_id: str | None = None,
) -> list[TagRowPayload]:
    """Emit rows for ``conditional_projections`` — item_type gated rules."""
    payloads: list[TagRowPayload] = []
    for rule in get_conditional_projections(table_name):
        when = rule.get("when", {})
        if not _matches_condition(record, when):
            continue
        value_field = rule.get("value_field", [])
        raw_value = _pick_conditional_value(record, value_field)
        if raw_value is None:
            continue
        payloads.extend(
            _emit_payloads_from_value(
                raw_value=raw_value,
                tag_types=rule.get("target_tag_types", []),
                target_type=target_type,
                target_id=target_id,
                asset_version_id=asset_version_id,
                source=source,
                confidence=None,
                extraction_run_id=None,
                trace_id=trace_id,
            )
        )
    return payloads


def project_record_to_tag_rows(
    *,
    table_name: str,
    record: Mapping[str, Any],
    target_id: str,
    asset_version_id: str,
    source: TagAssetIndexSource = TagAssetIndexSource.FIELD_PROJECTION,
    target_type: TagAssetIndexTargetType | None = None,
    trace_id: str | None = None,
) -> list[TagRowPayload]:
    """Top-level entry: emit *all* projection rows for one record.

    Emits both ``field_projections`` and ``conditional_projections``.
    Guaranteed deduplication within one call: rows with the same
    ``(tag_type, tag_value_normalized)`` are collapsed and the **first
    emission wins** (source ordering preserves the declared field order
    in the whitelist).

    Deduplication rules used by I-10 idempotency at the caller layer:
    a stable output means re-invoking the engine on the same input
    yields byte-identical rows.
    """
    if table_name not in PROJECTION_WHITELIST_V1_3:
        raise KeyError(f"table {table_name!r} has no projection whitelist entry")

    resolved_target_type = target_type or _TABLE_TO_TARGET_TYPE.get(table_name)
    if resolved_target_type is None:
        raise ValueError(
            f"table {table_name!r} has a whitelist entry but no target_type mapping; "
            "either register it in _TABLE_TO_TARGET_TYPE or pass target_type="
            "explicitly (major_profile_ability normally uses NORMALIZED_ASSET_REF)"
        )

    field_payloads = project_field_projections(
        table_name=table_name,
        record=record,
        target_type=resolved_target_type,
        target_id=target_id,
        asset_version_id=asset_version_id,
        source=source,
        trace_id=trace_id,
    )
    conditional_payloads = project_conditional_projections(
        table_name=table_name,
        record=record,
        target_type=resolved_target_type,
        target_id=target_id,
        asset_version_id=asset_version_id,
        source=source,
        trace_id=trace_id,
    )
    metadata_payloads = project_metadata_projections(
        table_name=table_name,
        record=record,
        target_type=resolved_target_type,
        target_id=target_id,
        asset_version_id=asset_version_id,
        source=source,
        trace_id=trace_id,
    )

    seen: set[tuple[str, str]] = set()
    deduplicated: list[TagRowPayload] = []
    for payload in field_payloads + conditional_payloads + metadata_payloads:
        key = (payload.tag_type, payload.tag_value_normalized)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(payload)
    return deduplicated


# ---------------------------------------------------------------------------
# Persistence (I-10 idempotency helper)
# ---------------------------------------------------------------------------


def persist_tag_rows(
    session: Session,
    payloads: list[TagRowPayload],
    *,
    target_type: TagAssetIndexTargetType,
    target_id: str,
    source: TagAssetIndexSource,
) -> int:
    """Delete-then-insert per ``(target_type, target_id, source)`` triple
    so re-running a writer projection yields the same row set.

    Returns the number of rows inserted.  Does **not** commit — the
    caller owns the transaction boundary (typically the writer's own
    session flush).

    Design note: caller passes the ``(target_type, target_id, source)``
    triple explicitly rather than letting us derive it from ``payloads``
    so that a projection producing **zero** rows (e.g. an all-null
    record) still cleans up the previous run.
    """
    # 1. Delete previous projection outputs for this triple.
    session.execute(
        delete(models.TagAssetIndex).where(
            models.TagAssetIndex.target_type == target_type,
            models.TagAssetIndex.target_id == target_id,
            models.TagAssetIndex.source == source,
        )
    )

    # 2. Insert new payload set.  Empty payloads => wipe-only, which is
    #    the correct behaviour when the source record loses all its
    #    taggable fields (e.g. all-null after re-normalisation).
    session.add_all(
        [
            models.TagAssetIndex(
                tag_type=p.tag_type,
                tag_value=p.tag_value,
                tag_value_normalized=p.tag_value_normalized,
                standard_code=p.standard_code,
                tag_embedding=None,  # async embedding worker fills in
                target_type=p.target_type,
                target_id=p.target_id,
                asset_version_id=p.asset_version_id,
                source=p.source,
                confidence=p.confidence,
                extraction_run_id=p.extraction_run_id,
                extracted_at=datetime.now(timezone.utc),
                trace_id=p.trace_id,
                evidence_span=p.evidence_span,
            )
            for p in payloads
        ]
    )
    session.flush()
    return len(payloads)
