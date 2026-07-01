"""Common chunk construction utility."""

from __future__ import annotations

from typing import Any

from nexus_app.enums import ChunkType, ChunkingStrategy, EmbeddingStatus, SourceKind
from nexus_app.models import KnowledgeChunk, new_uuid


def build_chunk(
    normalized_ref_id: str,
    emission: dict[str, Any],
    kt_config: Any,
    *,
    chunk_type: ChunkType,
    index: int,
    content: str,
    extra_metadata: dict[str, Any] | None = None,
    source_blocks: list[dict[str, Any]] | None = None,
    heading_path: list[dict[str, Any]] | None = None,
    md_spans: list[dict[str, Any]] | None = None,
    anchor_role: str | None = None,
    caption: str | None = None,
    chunking_strategy: ChunkingStrategy | None = None,
) -> KnowledgeChunk:
    """Construct a KnowledgeChunk with standard fields populated.

    Args:
        source_blocks: list of origin block descriptors from
            normalized_document.blocks[]. Each item should contain at least
            ``block_id`` and may include ``page``, ``bbox``, ``md_char_range``,
            ``block_type``. When provided, ``source_block_ids`` and
            ``locator`` are populated; otherwise both stay null (legitimate
            for record-pipeline chunks).
        heading_path / md_spans / anchor_role / caption: slice-2 locator-
            contract extensions (see docs/rag_semantic_chunks_implementation_plan
            §二.1). ``heading_path`` lands in ``locator``; ``anchor_role`` and
            ``caption`` live in ``chunk_metadata`` to avoid namespace clash.
        chunking_strategy: overrides ``kt_config.chunking_strategy`` — needed
            because semantic-repack-produced chunks declare strategy
            ``SEMANTIC_REPACK`` even when the host KT config still names
            ``passthrough_to_ragflow`` (KT config is end-user facing; chunk
            strategy is system-facing provenance).
    """
    meta: dict[str, Any] = {
        "chunking_config_snapshot": kt_config.chunking_config,
        "co_emission_origin": emission.get("co_emission_origin"),
    }
    if anchor_role is not None:
        meta["anchor_role"] = anchor_role
    if caption is not None:
        meta["caption"] = caption
    if extra_metadata:
        meta.update(extra_metadata)

    source_block_ids: list[str] | None = None
    locator: dict[str, Any] | None = None
    if source_blocks:
        source_block_ids = [
            b["block_id"] for b in source_blocks if b.get("block_id")
        ] or None
        locator = _aggregate_locator(
            source_blocks,
            heading_path=heading_path,
            md_spans=md_spans,
        )

    strategy = chunking_strategy or ChunkingStrategy(kt_config.chunking_strategy)

    return KnowledgeChunk(
        id=new_uuid(),
        normalized_ref_id=normalized_ref_id,
        knowledge_type_code=emission["code"],
        chunk_type=chunk_type,
        chunking_strategy=strategy,
        source_kind=SourceKind(kt_config.source_kind),
        chunk_index=index,
        content=content,
        chunk_metadata=meta,
        co_emission_origin=emission.get("co_emission_origin"),
        embedding_status=EmbeddingStatus.PENDING,
        source_block_ids=source_block_ids,
        locator=locator,
    )


def _aggregate_locator(
    blocks: list[dict[str, Any]],
    *,
    heading_path: list[dict[str, Any]] | None = None,
    md_spans: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate per-block page/bbox/md_char_range into the chunk-level locator.

    Slice-2 contract (see docs/rag_semantic_chunks_implementation_plan §二.1):

        {
            "page_start":     int | None,
            "page_end":       int | None,
            "bbox_union":     [x0,y0,x1,y1] | None,
            "blocks":         [{block_id, page, bbox, md_char_range}, ...],
            "md_char_range":  [start, end] | None,
            "md_spans":       [{start,end,block_id}, ...] | None,
            "heading_path":   [{level,title}, ...],
        }

    Invariants:
      - ``bbox_union`` is computed only when all source blocks share a single
        page (cross-page chunks fall back to per-block bboxes via ``blocks``).
      - ``md_char_range`` is the [min(start), max(end)] envelope of all
        contributing blocks' ranges; ``md_spans`` lists per-block sub-ranges
        (populated only for merged / multi-block chunks).
      - ``heading_path`` defaults to ``[]`` (stable field for serialisation).
    """
    normalized = [
        {
            "block_id": b.get("block_id"),
            "page": b.get("page"),
            "bbox": b.get("bbox"),
            "md_char_range": b.get("md_char_range"),
        }
        for b in blocks
    ]
    pages = [b["page"] for b in normalized if isinstance(b["page"], int)]
    page_start = min(pages) if pages else None
    page_end = max(pages) if pages else None

    bbox_union: list[float] | None = None
    if pages and len(set(pages)) == 1:
        valid = [b["bbox"] for b in normalized if _is_bbox(b["bbox"])]
        if valid:
            bbox_union = [
                min(box[0] for box in valid),
                min(box[1] for box in valid),
                max(box[2] for box in valid),
                max(box[3] for box in valid),
            ]

    md_char_range: list[int] | None = None
    ranges = [
        b["md_char_range"] for b in normalized
        if isinstance(b.get("md_char_range"), (list, tuple))
        and len(b["md_char_range"]) == 2
    ]
    if ranges:
        md_char_range = [
            min(r[0] for r in ranges),
            max(r[1] for r in ranges),
        ]

    return {
        "page_start": page_start,
        "page_end": page_end,
        "bbox_union": bbox_union,
        "blocks": normalized,
        "md_char_range": md_char_range,
        "md_spans": md_spans,
        "heading_path": heading_path or [],
    }


def _is_bbox(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 4
        and all(isinstance(v, (int, float)) for v in value)
    )


# ---------------------------------------------------------------------------
# Stage 2.2 reverse-mapping helper: span → source blocks via md_char_range
# ---------------------------------------------------------------------------

_UNSET = object()


def resolve_blocks_for_span(
    content_blocks: list[dict[str, Any]] | None,
    span: tuple[int, int],
    *,
    doc_fallback: list[dict[str, Any]] | None | object = _UNSET,
) -> list[dict[str, Any]] | None:
    """Reverse-lookup blocks whose ``md_char_range`` overlaps ``span``.

    Uses the out-of-band ``block["md_char_range"] = [start, end]`` annotation
    written by ``mineru_converter._annotate_md_ranges``. The markdown stream
    itself never carries anchors — this lookup is purely metadata-driven.

    Args:
        content_blocks: ``normalized_document.blocks[]`` for the underlying
            document; blocks without ``md_char_range`` are ignored.
        span: ``(start, end)`` character offsets in ``body_markdown`` (the
            same string those blocks index into).
        doc_fallback: returned when no block overlaps ``span``, OR when
            ``content_blocks`` is None / empty. Omitting the kwarg defaults
            to ``content_blocks`` (document-level fallback). Passing an
            explicit ``None`` disables fallback — useful when callers want
            to distinguish "primary" matches from a wider candidate set
            (e.g. graph_extract's primary-vs-evidence partition).

    Returns:
        Sublist of ``content_blocks`` whose ranges overlap, in original order.
        ``None`` when nothing resolves and ``doc_fallback`` is also empty.
    """
    if doc_fallback is _UNSET:
        fallback: list[dict[str, Any]] | None = content_blocks
    else:
        fallback = doc_fallback  # type: ignore[assignment]

    if not content_blocks:
        return fallback or None
    s, e = span
    if e <= s:
        return fallback or None
    hits: list[dict[str, Any]] = []
    for block in content_blocks:
        r = block.get("md_char_range")
        if not r or len(r) != 2:
            continue
        bs, be = r[0], r[1]
        if be <= s or bs >= e:
            continue
        hits.append(block)
    return hits or (fallback or None)
