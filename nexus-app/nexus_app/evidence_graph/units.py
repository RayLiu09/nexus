"""Contextual extraction units for Evidence-grounded KG.

RAG chunks remain the evidence and locator boundary. Graph extraction uses
larger runtime units so LLM extractors see section/window context instead of
isolated chunks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha1
from typing import Any

from nexus_app.evidence_graph.candidates import GraphChunkCandidate
from nexus_app.evidence_graph.profiles import AnchorRole, ExtractionMethod

DEFAULT_MAX_UNIT_CHARS = 24000
DEFAULT_MAX_CHUNKS_PER_UNIT = 24
DEFAULT_OVERLAP_CHUNKS = 1


@dataclass(frozen=True)
class GraphExtractionUnit:
    unit_id: str
    normalized_ref_id: str
    unit_type: str
    graph_profile: str
    extractor_name: str
    extraction_method: str
    anchor_role: str
    anchor_roles: tuple[str, ...]
    heading_path: tuple[str, ...]
    chunk_ids: tuple[str, ...]
    primary_chunk_id: str
    chunk_index_start: int
    chunk_index_end: int
    content: str
    chunks: tuple[GraphChunkCandidate, ...]
    source_block_ids: tuple[str, ...]
    locator: dict[str, Any] | None

    @property
    def chunk_id(self) -> str:
        return self.primary_chunk_id

    @property
    def chunk_index(self) -> int:
        return self.chunk_index_start

    @property
    def knowledge_type_code(self) -> str:
        return self.chunks[0].knowledge_type_code if self.chunks else ""


@dataclass(frozen=True)
class UnitGroupingSummary:
    source_candidate_chunks: int
    extraction_unit_count: int
    avg_chunks_per_unit: float
    max_chunks_per_unit: int
    by_unit_type: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_candidate_chunks": self.source_candidate_chunks,
            "extraction_unit_count": self.extraction_unit_count,
            "avg_chunks_per_unit": self.avg_chunks_per_unit,
            "max_chunks_per_unit": self.max_chunks_per_unit,
            "by_unit_type": self.by_unit_type,
        }


def group_graph_extraction_units(
    candidates: tuple[GraphChunkCandidate, ...] | list[GraphChunkCandidate],
    *,
    graph_profile: str,
    max_unit_chars: int = DEFAULT_MAX_UNIT_CHARS,
    max_chunks_per_unit: int = DEFAULT_MAX_CHUNKS_PER_UNIT,
    overlap_chunks: int = DEFAULT_OVERLAP_CHUNKS,
) -> tuple[GraphExtractionUnit, ...]:
    """Group ordered chunk candidates into graph extraction context units.

    Stage 1 groups only body LLM chunks because they suffer most from context
    fragmentation. Rule-based table/image/metric candidates remain one unit per
    chunk to preserve established parsing behavior.
    """
    if max_unit_chars <= 0:
        raise ValueError("max_unit_chars must be positive")
    if max_chunks_per_unit <= 0:
        raise ValueError("max_chunks_per_unit must be positive")
    if overlap_chunks < 0:
        raise ValueError("overlap_chunks must not be negative")

    ordered = sorted(candidates, key=lambda item: item.chunk_index)
    units: list[GraphExtractionUnit] = []
    body_buffer: list[GraphChunkCandidate] = []
    body_heading: tuple[str, ...] | None = None

    def flush_body() -> None:
        nonlocal body_buffer, body_heading
        if body_buffer:
            units.extend(_split_body_windows(
                body_buffer,
                graph_profile=graph_profile,
                heading_path=body_heading or (),
                max_unit_chars=max_unit_chars,
                max_chunks_per_unit=max_chunks_per_unit,
                overlap_chunks=overlap_chunks,
            ))
        body_buffer = []
        body_heading = None

    for candidate in ordered:
        if _is_body_llm_candidate(candidate):
            heading = _heading_path(candidate)
            if body_buffer and (
                heading != body_heading
                or candidate.chunk_index != body_buffer[-1].chunk_index + 1
            ):
                flush_body()
            body_buffer.append(candidate)
            body_heading = heading
            continue

        flush_body()
        units.append(_single_chunk_unit(candidate, graph_profile=graph_profile))

    flush_body()
    return tuple(units)


def summarize_units(
    units: tuple[GraphExtractionUnit, ...] | list[GraphExtractionUnit],
    *,
    source_candidate_chunks: int,
) -> UnitGroupingSummary:
    by_unit_type: dict[str, int] = {}
    max_chunks = 0
    total_chunks = 0
    for unit in units:
        by_unit_type[unit.unit_type] = by_unit_type.get(unit.unit_type, 0) + 1
        chunk_count = len(unit.chunk_ids)
        total_chunks += chunk_count
        max_chunks = max(max_chunks, chunk_count)
    avg = round(total_chunks / len(units), 4) if units else 0.0
    return UnitGroupingSummary(
        source_candidate_chunks=source_candidate_chunks,
        extraction_unit_count=len(units),
        avg_chunks_per_unit=avg,
        max_chunks_per_unit=max_chunks,
        by_unit_type=by_unit_type,
    )


def _is_body_llm_candidate(candidate: GraphChunkCandidate) -> bool:
    return (
        candidate.anchor_role == AnchorRole.BODY
        and candidate.extraction_method == ExtractionMethod.LLM
    )


def _split_body_windows(
    candidates: list[GraphChunkCandidate],
    *,
    graph_profile: str,
    heading_path: tuple[str, ...],
    max_unit_chars: int,
    max_chunks_per_unit: int,
    overlap_chunks: int,
) -> list[GraphExtractionUnit]:
    units: list[GraphExtractionUnit] = []
    current: list[GraphChunkCandidate] = []
    current_chars = 0

    for candidate in candidates:
        candidate_chars = len(candidate.content or "")
        would_exceed_chars = current and current_chars + candidate_chars > max_unit_chars
        would_exceed_count = current and len(current) >= max_chunks_per_unit
        if would_exceed_chars or would_exceed_count:
            units.append(_unit_from_chunks(
                current,
                graph_profile=graph_profile,
                unit_type="section" if len(units) == 0 else "sliding_window",
                heading_path=heading_path,
            ))
            carry = current[-overlap_chunks:] if overlap_chunks else []
            current = list(carry)
            current_chars = sum(len(item.content or "") for item in current)
        current.append(candidate)
        current_chars += candidate_chars

    if current:
        units.append(_unit_from_chunks(
            current,
            graph_profile=graph_profile,
            unit_type="section" if len(units) == 0 else "sliding_window",
            heading_path=heading_path,
        ))
    return units


def _single_chunk_unit(
    candidate: GraphChunkCandidate,
    *,
    graph_profile: str,
) -> GraphExtractionUnit:
    unit_type = {
        AnchorRole.TABLE_ROW: "table_row",
        AnchorRole.METRIC_IMAGE: "visual_context",
        AnchorRole.CHART: "visual_context",
        AnchorRole.IMAGE: "visual_context",
    }.get(candidate.anchor_role, "chunk")
    return _unit_from_chunks(
        [candidate],
        graph_profile=graph_profile,
        unit_type=unit_type,
        heading_path=_heading_path(candidate),
    )


def _unit_from_chunks(
    chunks: list[GraphChunkCandidate],
    *,
    graph_profile: str,
    unit_type: str,
    heading_path: tuple[str, ...],
) -> GraphExtractionUnit:
    if not chunks:
        raise ValueError("GraphExtractionUnit requires at least one chunk")
    chunk_ids = tuple(chunk.chunk_id for chunk in chunks)
    anchor_roles = tuple(dict.fromkeys(chunk.anchor_role for chunk in chunks))
    source_block_ids = tuple(_dedupe(
        block_id
        for chunk in chunks
        for block_id in (chunk.source_block_ids or [])
    ))
    content = _render_unit_content(chunks)
    return GraphExtractionUnit(
        unit_id=f"{unit_type}:{chunks[0].chunk_index}:{chunks[-1].chunk_index}:{_stable_id(chunk_ids)}",
        normalized_ref_id=chunks[0].normalized_ref_id,
        unit_type=unit_type,
        graph_profile=graph_profile,
        extractor_name=chunks[0].extractor_name,
        extraction_method=chunks[0].extraction_method,
        anchor_role=chunks[0].anchor_role,
        anchor_roles=anchor_roles,
        heading_path=heading_path,
        chunk_ids=chunk_ids,
        primary_chunk_id=chunks[0].chunk_id,
        chunk_index_start=chunks[0].chunk_index,
        chunk_index_end=chunks[-1].chunk_index,
        content=content,
        chunks=tuple(chunks),
        source_block_ids=source_block_ids,
        locator=_aggregate_locator(chunks),
    )


def _render_unit_content(chunks: list[GraphChunkCandidate]) -> str:
    if len(chunks) == 1:
        return chunks[0].content
    parts = []
    for chunk in chunks:
        parts.append(
            f"[chunk_id={chunk.chunk_id}; chunk_index={chunk.chunk_index}; "
            f"anchor_role={chunk.anchor_role}]\n{chunk.content}"
        )
    return "\n\n".join(parts)


def _heading_path(candidate: GraphChunkCandidate) -> tuple[str, ...]:
    locator = candidate.locator or {}
    metadata = candidate.chunk_metadata or {}
    metadata_heading = locator.get("heading_path") or metadata.get("heading_path")
    if isinstance(metadata_heading, list):
        values: list[str] = []
        for item in metadata_heading:
            if isinstance(item, dict):
                title = item.get("title")
                if title:
                    values.append(str(title))
            elif item:
                values.append(str(item))
        return tuple(values)
    if isinstance(metadata_heading, str) and metadata_heading.strip():
        return (metadata_heading.strip(),)
    return ()


def _aggregate_locator(chunks: list[GraphChunkCandidate]) -> dict[str, Any] | None:
    locators = [chunk.locator for chunk in chunks if chunk.locator]
    if not locators:
        return None
    page_starts = [loc.get("page_start") for loc in locators if isinstance(loc.get("page_start"), int)]
    page_ends = [loc.get("page_end") for loc in locators if isinstance(loc.get("page_end"), int)]
    blocks = []
    heading_path = None
    for locator in locators:
        if heading_path is None and locator.get("heading_path") is not None:
            heading_path = locator.get("heading_path")
        value = locator.get("blocks")
        if isinstance(value, list):
            blocks.extend(item for item in value if isinstance(item, dict))
    result: dict[str, Any] = {
        "chunks": [chunk.chunk_id for chunk in chunks],
    }
    if page_starts:
        result["page_start"] = min(page_starts)
    if page_ends:
        result["page_end"] = max(page_ends)
    if blocks:
        result["blocks"] = blocks
    if heading_path is not None:
        result["heading_path"] = heading_path
    return result


def _stable_id(values: tuple[str, ...]) -> str:
    return sha1(json.dumps(values, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def _dedupe(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
