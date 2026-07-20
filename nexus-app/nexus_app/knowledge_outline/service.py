"""Knowledge outline persistence + API-facing service.

Consumed by ``nexus-api`` GET (auto-build on first hit) and POST rebuild.
Never invoked from the pipeline — construction is synchronous, gated on
``task_outline_profile.textbook_subtype == "theory_knowledge"``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.outline_projection import (
    project_and_persist_outline_nodes,
)
from nexus_app.audit import write_audit
from nexus_app.enums import AuditEventType
from nexus_app.knowledge_outline.builder import (
    HeadingInput,
    OutlineBuildResult,
    OutlineNodeSpec,
    build_outline,
)

# Subtypes eligible for the knowledge-outline view. ``theory_knowledge`` is
# the primary target; ``hybrid`` textbooks also benefit (the LLM v2 path
# handles them cleanly — chapters + knowledge points come out well even
# when a task-outline layer is intermixed).
TEXTBOOK_SUBTYPE_GATE = "theory_knowledge"  # kept for backward compat
KNOWLEDGE_OUTLINE_ELIGIBLE_SUBTYPES = frozenset({"theory_knowledge", "hybrid"})
TASK_OUTLINE_ASSET_PROFILE = "course_textbook"
HEADING_BLOCK_TYPES = {"heading", "title"}


# ---------------------------------------------------------------------------
# Read models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OutlineNodeRead:
    id: str
    parent_id: str | None
    level: int
    order_index: int
    title: str
    numbering: str | None
    numbering_path: list[int] | None
    anchor_range: dict[str, Any] | None
    chunk_count: int


@dataclass(frozen=True)
class OutlineTree:
    ref_id: str
    build_run_id: str
    total_nodes: int
    max_depth: int
    fallback_used: bool
    root_id: str
    nodes: list[OutlineNodeRead]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def has_theory_knowledge_profile(session: Session, ref_id: str) -> bool:
    """Return True when the ref has a course_textbook profile whose
    ``textbook_subtype`` matches the gate value."""
    row = session.scalar(
        select(models.TaskOutlineProfile.textbook_subtype)
        .where(
            models.TaskOutlineProfile.normalized_ref_id == ref_id,
            models.TaskOutlineProfile.asset_profile == TASK_OUTLINE_ASSET_PROFILE,
        )
    )
    return row in KNOWLEDGE_OUTLINE_ELIGIBLE_SUBTYPES


def get_outline_tree(session: Session, ref_id: str) -> OutlineTree | None:
    """Return the persisted outline tree for a ref, or None if not built."""
    rows = list(session.scalars(
        select(models.KnowledgeOutlineNode)
        .where(models.KnowledgeOutlineNode.normalized_ref_id == ref_id)
        .order_by(
            models.KnowledgeOutlineNode.level.asc(),
            models.KnowledgeOutlineNode.order_index.asc(),
            models.KnowledgeOutlineNode.id.asc(),
        )
    ))
    if not rows:
        return None
    return _rows_to_tree(rows)


def build_and_persist_outline(
    session: Session,
    *,
    ref: models.NormalizedAssetRef,
    payload: dict[str, Any],
    rules_etag: str | None,
    trace_id: str | None = None,
    actor_type: str | None = None,
    actor_id: str | None = None,
    is_rebuild: bool = False,
) -> OutlineTree:
    """Build the outline from payload, replace any existing tree, and audit.

    Caller MUST have already verified the theory_knowledge gate. Runs in the
    caller's session; caller commits.
    """
    if is_rebuild:
        write_audit(
            session,
            AuditEventType.KNOWLEDGE_OUTLINE_REBUILD_REQUESTED,
            "normalized_asset_ref",
            ref.id,
            trace_id,
            {"ref_id": ref.id, "rules_etag": rules_etag},
            actor_type=actor_type,
            actor_id=actor_id,
        )

    root_title = _root_title_for(payload, ref)
    blocks = _blocks_from_payload(payload)
    headings, chunk_associations = _prepare_headings(session, ref.id, blocks)

    result = build_outline(headings, root_title=root_title)

    _replace_outline_rows(session, ref.id, result)
    leaf_backfill_count = _apply_chunk_backfill(
        session,
        ref_id=ref.id,
        result=result,
        chunk_associations=chunk_associations,
    )

    # v1.3 PR-7 — project title → topic tag rows onto tag_asset_index
    # so the retrieval-side unstructured OUTLINE_NODE anchor can find
    # these nodes.  Best-effort: an exception here would waste the
    # already-persisted outline; wrap so the write_audit still fires.
    projection = _project_outline_tags(
        session,
        nodes=result.nodes,
        asset_version_id=ref.version_id,
        trace_id=trace_id,
    )

    write_audit(
        session,
        AuditEventType.KNOWLEDGE_OUTLINE_BUILT,
        "normalized_asset_ref",
        ref.id,
        trace_id,
        {
            "ref_id": ref.id,
            "build_run_id": result.build_run_id,
            "node_count": result.total_nodes,
            "max_depth": result.max_depth,
            "fallback_used": result.fallback_used,
            "leaf_chunk_backfill_count": leaf_backfill_count,
            "rules_etag": rules_etag,
            # PR-7 observability — surfaces both the projection outcome
            # and any degradation so the audit alone explains missing
            # tag rows.
            "tag_projection": {
                "node_count": projection.node_count,
                "rows_persisted": projection.rows_persisted,
                "empty_title_count": projection.empty_title_count,
                "error": projection.error,
            },
        },
        actor_type=actor_type,
        actor_id=actor_id,
    )

    return _rows_to_tree(_reload_nodes(session, ref.id))


# ---------------------------------------------------------------------------
# Heading extraction + chunk association
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ChunkAssociation:
    """Ordered list of (chunk_id, heading_index) belonging to each heading."""

    by_heading_index: dict[int, list[str]] = field(default_factory=dict)


def _blocks_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = payload.get("blocks")
    if isinstance(blocks, list):
        return [b for b in blocks if isinstance(b, dict)]
    return []


def _prepare_headings(
    session: Session,
    ref_id: str,
    blocks: list[dict[str, Any]],
) -> tuple[list[HeadingInput], _ChunkAssociation]:
    heading_indices = [
        i for i, block in enumerate(blocks)
        if _block_type(block) in HEADING_BLOCK_TYPES and _block_text(block)
    ]

    # Map each block_id to the heading it belongs to (index in the heading list).
    block_to_heading_idx: dict[str, int] = {}
    heading_spans: list[list[dict[str, Any]]] = []
    for pos, hi in enumerate(heading_indices):
        next_hi = heading_indices[pos + 1] if pos + 1 < len(heading_indices) else len(blocks)
        span_blocks = blocks[hi:next_hi]
        heading_spans.append(span_blocks)
        for block in span_blocks:
            bid = block.get("block_id")
            if isinstance(bid, str) and bid not in block_to_heading_idx:
                block_to_heading_idx[bid] = pos

    # Associate existing chunks with their owning heading by block-id intersection.
    associations = _ChunkAssociation()
    heading_title_positions: dict[str, list[int]] = {}
    for position, heading_index in enumerate(heading_indices):
        key = _normalise_heading_title(_block_text(blocks[heading_index]))
        if key:
            heading_title_positions.setdefault(key, []).append(position)
    chunks = list(session.scalars(
        select(models.KnowledgeChunk)
        .where(models.KnowledgeChunk.normalized_ref_id == ref_id)
    ))
    for chunk in chunks:
        heading_idx = _unique_locator_heading_target(
            chunk, heading_title_positions,
        )
        if heading_idx is not None:
            associations.by_heading_index.setdefault(heading_idx, []).append(chunk.id)
            continue
        source_ids = chunk.source_block_ids or []
        for bid in source_ids:
            key = str(bid)
            if key in block_to_heading_idx:
                heading_idx = block_to_heading_idx[key]
                associations.by_heading_index.setdefault(heading_idx, []).append(chunk.id)
                break  # first-match wins

    headings: list[HeadingInput] = []
    for pos, hi in enumerate(heading_indices):
        block = blocks[hi]
        title = _block_text(block).strip()
        level = _heading_level(block) or 1
        span = heading_spans[pos]
        anchor = _compute_anchor(span)
        source_block_ids = [
            str(b.get("block_id")) for b in span if b.get("block_id")
        ]
        headings.append(
            HeadingInput(
                title=title,
                level=level,
                anchor_range=anchor,
                source_block_ids=source_block_ids,
                chunk_ids=associations.by_heading_index.get(pos, []),
            )
        )

    return headings, associations


def _normalise_heading_title(value: str) -> str:
    return re.sub(r"[\s，,。.:：；;、]", "", value).lower()


def _locator_heading_keys(chunk: models.KnowledgeChunk) -> list[str]:
    """Return deepest-first normalized source heading titles for a chunk."""
    raw_path = (chunk.locator or {}).get("heading_path")
    if not isinstance(raw_path, list):
        raw_path = (chunk.chunk_metadata or {}).get("heading_path")
    if not isinstance(raw_path, list):
        return []
    keys: list[str] = []
    for item in reversed(raw_path):
        title = item.get("title") if isinstance(item, dict) else None
        if isinstance(title, str):
            key = _normalise_heading_title(title)
            if key:
                keys.append(key)
    return keys


def _unique_locator_heading_target(
    chunk: models.KnowledgeChunk,
    targets: dict[str, list[Any]],
) -> Any | None:
    """Map a chunk's deepest uniquely-known locator title to a target."""
    for key in _locator_heading_keys(chunk):
        matches = targets.get(key, [])
        if len(matches) == 1:
            return matches[0]
    return None


def _root_title_for(payload: dict[str, Any], ref: models.NormalizedAssetRef) -> str:
    for key in ("title", "asset_title", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "全文"


def _block_type(block: dict[str, Any]) -> str:
    value = block.get("block_type") or block.get("type") or ""
    return str(value).lower()


def _block_text(block: dict[str, Any]) -> str:
    for key in ("text", "content", "value"):
        value = block.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _heading_level(block: dict[str, Any]) -> int | None:
    raw = block.get("heading_level")
    level: int | None = None
    if isinstance(raw, int) and raw > 0:
        level = raw
    elif isinstance(raw, str) and raw.isdigit():
        parsed = int(raw)
        level = parsed if parsed > 0 else None
    if level is None:
        return None
    title = _block_text(block).strip()
    if re.match(r"^\d+\s*[.．、]", title) or re.match(r"^（\d+）", title):
        return level + 1
    if re.match(r"^[①②③④⑤⑥⑦⑧⑨⑩]", title):
        return level + 2
    return level


def _compute_anchor(blocks_in_span: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not blocks_in_span:
        return None
    block_ids = [str(b.get("block_id")) for b in blocks_in_span if b.get("block_id")]
    pages = [
        b.get("page") for b in blocks_in_span
        if isinstance(b.get("page"), int)
    ]
    payload: dict[str, Any] = {}
    if block_ids:
        payload["block_ids"] = block_ids
    if pages:
        payload["page_start"] = min(pages)
        payload["page_end"] = max(pages)
    return payload or None


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _OutlineTagProjectionSummary:
    node_count: int
    rows_persisted: int
    empty_title_count: int
    error: str | None


def _project_outline_tags(
    session: Session,
    *,
    nodes: list[OutlineNodeSpec],
    asset_version_id: str | None,
    trace_id: str | None,
) -> _OutlineTagProjectionSummary:
    """Run PR-7 outline tag projection.  Never raises — errors are
    captured on the summary so the caller's audit event still fires and
    the outline build isn't reverted."""
    if not asset_version_id:
        return _OutlineTagProjectionSummary(
            node_count=0, rows_persisted=0, empty_title_count=0,
            error="missing_asset_version_id",
        )
    try:
        result = project_and_persist_outline_nodes(
            session,
            table_name="knowledge_outline_node",
            nodes=nodes,
            asset_version_id=asset_version_id,
            trace_id=trace_id,
        )
    except Exception as exc:  # noqa: BLE001 - projection must never abort the build
        return _OutlineTagProjectionSummary(
            node_count=0, rows_persisted=0, empty_title_count=0,
            error=f"{type(exc).__name__}: {exc}",
        )
    return _OutlineTagProjectionSummary(
        node_count=result.node_count,
        rows_persisted=result.rows_persisted,
        empty_title_count=result.empty_title_count,
        error=None,
    )


def _replace_outline_rows(
    session: Session,
    ref_id: str,
    result: OutlineBuildResult,
) -> None:
    # Detach chunks first; the FK is ON DELETE SET NULL so the DB would do this
    # anyway, but explicit clearing keeps the SQL cache/plan simple and lets us
    # measure backfill against a known-zero baseline.
    session.execute(
        update(models.KnowledgeChunk)
        .where(models.KnowledgeChunk.normalized_ref_id == ref_id)
        .values(knowledge_outline_node_id=None)
    )
    session.execute(
        delete(models.KnowledgeOutlineNode)
        .where(models.KnowledgeOutlineNode.normalized_ref_id == ref_id)
    )
    session.flush()

    for spec in result.nodes:
        session.add(_spec_to_row(
            spec,
            ref_id=ref_id,
            build_run_id=result.build_run_id,
            fallback_used=result.fallback_used,
        ))
    session.flush()


def _spec_to_row(
    spec: OutlineNodeSpec,
    *,
    ref_id: str,
    build_run_id: str,
    fallback_used: bool,
) -> models.KnowledgeOutlineNode:
    return models.KnowledgeOutlineNode(
        id=spec.id,
        normalized_ref_id=ref_id,
        parent_id=spec.parent_id,
        level=spec.level,
        order_index=spec.order_index,
        title=spec.title,
        numbering=spec.numbering,
        numbering_path=spec.numbering_path,
        anchor_range=spec.anchor_range,
        chunk_count=len(spec.chunk_ids),
        build_run_id=build_run_id,
        fallback_used=fallback_used,
        node_metadata=(
            {"source_block_ids": spec.source_block_ids}
            if spec.source_block_ids else {}
        ),
    )


def _apply_chunk_backfill(
    session: Session,
    *,
    ref_id: str,
    result: OutlineBuildResult,
    chunk_associations: _ChunkAssociation,
) -> int:
    backfill_count = 0
    for spec in result.nodes:
        if not spec.chunk_ids:
            continue
        # spec.chunk_ids only survives for leaves (builder cleared them on
        # non-leaves), but assert to keep the invariant loud.
        session.execute(
            update(models.KnowledgeChunk)
            .where(
                models.KnowledgeChunk.id.in_(spec.chunk_ids),
                models.KnowledgeChunk.normalized_ref_id == ref_id,
            )
            .values(knowledge_outline_node_id=spec.id)
        )
        backfill_count += len(spec.chunk_ids)
    return backfill_count


def _reload_nodes(
    session: Session, ref_id: str,
) -> list[models.KnowledgeOutlineNode]:
    return list(session.scalars(
        select(models.KnowledgeOutlineNode)
        .where(models.KnowledgeOutlineNode.normalized_ref_id == ref_id)
        .order_by(
            models.KnowledgeOutlineNode.level.asc(),
            models.KnowledgeOutlineNode.order_index.asc(),
            models.KnowledgeOutlineNode.id.asc(),
        )
    ))


def _rows_to_tree(rows: list[models.KnowledgeOutlineNode]) -> OutlineTree:
    assert rows, "caller must ensure non-empty rows"
    root = next(r for r in rows if r.parent_id is None)
    nodes = [
        OutlineNodeRead(
            id=r.id,
            parent_id=r.parent_id,
            level=r.level,
            order_index=r.order_index,
            title=r.title,
            numbering=r.numbering,
            numbering_path=r.numbering_path,
            anchor_range=r.anchor_range,
            chunk_count=r.chunk_count,
        )
        for r in rows
    ]
    return OutlineTree(
        ref_id=root.normalized_ref_id,
        build_run_id=root.build_run_id,
        total_nodes=len(rows),
        max_depth=max((r.level for r in rows), default=0),
        fallback_used=root.fallback_used,
        root_id=root.id,
        nodes=nodes,
    )
