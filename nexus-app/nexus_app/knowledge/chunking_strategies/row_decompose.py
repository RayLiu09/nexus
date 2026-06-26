"""Tier-A: row_decompose strategy for record-pipeline KTs.

Pipeline B record-pipeline KTs (e.g. ``structured_record_table`` for
job_demand) declare ``chunking_mode=row_per_chunk`` +
``chunking_strategy=row_decompose`` in ``governance_rules_v2.json``. Each row
in the normalized record body becomes one ``STRUCTURED_RECORD_ROW`` chunk so
RAG retrieval can return individual records as standalone hits.

Contract:
- Input source priority:
    1. ``record_body`` kwarg (the structured dict / list piped through from
       ``pipeline/stages.py:_load_normalized_payload``). This is the
       canonical source and what production callers pass.
    2. ``content`` — fallback for callers that still hand the strategy a
       JSON string (older tests, debugging harnesses). Useful because the
       record pipeline's body_markdown override means ``content`` may NOT
       be the JSON for production refs once B5.3 has rendered markdown.
- We accept both shapes:
    * ``{"dataset": {...}, "records": [...]}`` — the job_demand B3.5
      projection.
    * ``[...]`` — a bare list of row dicts (defensive: future writers).
- Each record becomes one chunk; ``content`` is rendered as
  ``"<header>: <value>\\n..."`` so RAGFlow's ``chunk_method=table`` ingestion
  has a stable canonical form. ``include_header_in_chunk`` (kt config) gates
  whether a dataset-level header line is prepended.
- ``source_blocks`` stays None — record pipeline carries no block locators;
  ``chunk_metadata`` keeps record-level provenance instead.

Cap: ``max_chunks_per_unit`` from KT config. When exceeded, the last chunk
is marked ``truncated=True`` so retrieval surfaces partial output rather
than silently dropping rows.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from nexus_app.enums import ChunkingStrategy, ChunkType
from nexus_app.knowledge.chunk_builder import build_chunk
from nexus_app.knowledge.registry import register_strategy
from nexus_app.models import KnowledgeChunk

logger = logging.getLogger(__name__)


# Fields that carry only system-side provenance, not retrieval-relevant
# content. Excluded from the rendered chunk body so the retrieval signal
# stays clean. They still surface in `chunk_metadata` for traceability.
_PROVENANCE_FIELDS: frozenset[str] = frozenset({
    "trace",
    "source_record_key",
    "source_url",
    "source_platform",
    "source_published_at",
})

_DEFAULT_ROW_SIZE_TARGET = 1


@register_strategy("row_decompose")
class RowDecomposeStrategy:
    """One record → one chunk. See module docstring for the contract."""

    def __init__(self, config: dict[str, Any]) -> None:
        # row_size_target preserved for future grouping support (rows per
        # chunk > 1). v1 always emits one row per chunk; values other than
        # 1 are accepted but treated as 1 so config evolves without code
        # changes when grouping ships.
        self.row_size_target = int(
            config.get("row_size_target", _DEFAULT_ROW_SIZE_TARGET)
        )
        self.include_header_in_chunk = bool(
            config.get("include_header_in_chunk", True)
        )

    def chunk(
        self,
        content: str,
        emission: dict[str, Any],
        kt_config: Any,
        normalized_ref_id: str,
        content_blocks: list[dict[str, Any]] | None = None,
        *,
        record_body: dict[str, Any] | list[Any] | None = None,
    ) -> list[KnowledgeChunk]:
        records, dataset = _resolve_record_body(record_body, content)
        if not records:
            return []

        max_chunks = kt_config.max_chunks_per_unit
        header_line = _build_header_line(dataset) if self.include_header_in_chunk else None

        chunks: list[KnowledgeChunk] = []
        for idx, record in enumerate(records):
            if len(chunks) >= max_chunks:
                # Cap-hit: mark the last emitted chunk so retrieval can
                # surface "partial output" instead of silently dropping
                # rows. Matches structured_decompose's truncated flag.
                if chunks:
                    chunks[-1].chunk_metadata["truncated"] = True
                break
            chunks.append(
                _build_record_chunk(
                    record=record,
                    dataset=dataset,
                    emission=emission,
                    kt_config=kt_config,
                    normalized_ref_id=normalized_ref_id,
                    index=idx,
                    header_line=header_line,
                )
            )
        return chunks


def _resolve_record_body(
    record_body: dict[str, Any] | list[Any] | None,
    content: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Pick records + dataset from the canonical record_body, falling back
    to JSON-parsing ``content`` when no structured input is given.

    Returns ``([], {})`` on any failure so the strategy emits zero chunks
    rather than raising — record-pipeline chunking is best-effort and
    shouldn't fail the whole job over a malformed payload (governance has
    already audited the source).
    """
    if record_body is not None:
        return _extract_records_and_dataset(record_body)
    if not content:
        return [], {}
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError):
        logger.warning("row_decompose: content is not valid JSON; emitting 0 chunks")
        return [], {}
    return _extract_records_and_dataset(parsed)


def _extract_records_and_dataset(
    payload: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Normalise the accepted shapes (dict-with-records / bare list) into
    the ``(records, dataset)`` tuple the chunker uses."""
    if isinstance(payload, dict):
        records = payload.get("records")
        dataset = payload.get("dataset") or {}
        if isinstance(records, list):
            return [r for r in records if isinstance(r, dict)], (
                dataset if isinstance(dataset, dict) else {}
            )
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)], {}
    return [], {}


def _build_header_line(dataset: dict[str, Any]) -> str | None:
    """Dataset-scope header surfaced once per chunk for retrieval context.

    Surfaces dataset.major_name / industry_name / source_channel when
    present (B3.5 ``_project_job_demand`` populates these from profile
    evidence). Returns None when the dataset offers no meaningful hint —
    callers then skip the header line entirely.
    """
    if not dataset:
        return None
    parts: list[str] = []
    if dataset.get("major_name"):
        parts.append(f"专业: {dataset['major_name']}")
    if dataset.get("industry_name"):
        parts.append(f"行业: {dataset['industry_name']}")
    if dataset.get("source_channel"):
        parts.append(f"来源: {dataset['source_channel']}")
    if not parts:
        return None
    return "[dataset] " + " | ".join(parts)


def _build_record_chunk(
    *,
    record: dict[str, Any],
    dataset: dict[str, Any],
    emission: dict[str, Any],
    kt_config: Any,
    normalized_ref_id: str,
    index: int,
    header_line: str | None,
) -> KnowledgeChunk:
    rendered = _render_record_content(record, header_line=header_line)
    source_record_key = record.get("source_record_key")
    trace = record.get("trace") if isinstance(record.get("trace"), dict) else None
    extra: dict[str, Any] = {
        # row_index_hint mirrors the trace.row if structured_parse provided
        # one — lets retrieval consumers correlate a chunk back to the
        # exact source row without re-parsing source_record_key strings.
        "row_index_hint": trace.get("row") if trace else None,
        "sheet_name": trace.get("sheet") if trace else None,
        "source_record_key": source_record_key,
        # Retain the raw record so downstream consumers (RAG re-ranking,
        # console preview) can render fields without re-fetching MinIO.
        # Audit sanitization keeps this safe for governance / audit logs.
        "record_fields": _filter_for_metadata(record),
    }
    return build_chunk(
        normalized_ref_id=normalized_ref_id,
        emission=emission,
        kt_config=kt_config,
        chunk_type=ChunkType.STRUCTURED_RECORD_ROW,
        chunking_strategy=ChunkingStrategy.ROW_DECOMPOSE,
        index=index,
        content=rendered,
        extra_metadata=extra,
        # Record pipeline carries no block locators — leave source_blocks
        # / heading_path / md_spans as None so locator stays null per
        # the chunk-locator contract for ``normalized_type=record``.
        source_blocks=None,
    )


def _render_record_content(
    record: dict[str, Any],
    *,
    header_line: str | None,
) -> str:
    """Render a single record as ``"<field>: <value>"`` lines.

    Ordering follows the record's dict iteration order so structured_parse's
    original column order is preserved (Python preserves insertion order on
    dict literals + the writers build records by walking column maps).
    Provenance keys are suppressed from the body to keep the retrieval
    signal focused on factual fields — they're still on the chunk's
    `chunk_metadata` for traceability.
    """
    lines: list[str] = []
    if header_line:
        lines.append(header_line)
    for key, value in record.items():
        if key in _PROVENANCE_FIELDS:
            continue
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            # Nested structures get JSON-dumped so RAGFlow's table parser
            # still sees a single-line value per field. Rare on the
            # job_demand projection but defensive for future profiles.
            value_str = json.dumps(value, ensure_ascii=False)
        else:
            value_str = str(value)
        lines.append(f"{key}: {value_str}")
    return "\n".join(lines)


def _filter_for_metadata(record: dict[str, Any]) -> dict[str, Any]:
    """Pick retrieval-relevant fields for chunk_metadata.record_fields.

    Excludes nested ``trace`` (it's already surfaced as sheet_name /
    row_index_hint on the metadata root) and source_record_key (mirrored
    above) so the metadata isn't double-stored.
    """
    return {
        k: v
        for k, v in record.items()
        if k not in {"trace", "source_record_key"} and v is not None
    }
