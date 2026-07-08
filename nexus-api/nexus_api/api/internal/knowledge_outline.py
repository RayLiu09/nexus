"""Knowledge Outline internal API for Console.

Sync construction: GET auto-builds the outline on first hit (gated by
``task_outline_profile.textbook_subtype == "theory_knowledge"``); POST
rebuild replaces the existing tree inline.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.responses import response
from nexus_api.api.internal._helpers import get_rules_registry
from nexus_app import models
from nexus_app.database import get_db
from nexus_app.enums import NormalizedType
from nexus_app.knowledge_outline.service import (
    OutlineNodeRead,
    OutlineTree,
    build_and_persist_outline,
    get_outline_tree,
    has_theory_knowledge_profile,
)

router = APIRouter()

PREVIEW_MAX_CHARS = 800
CHUNK_PAGE_DEFAULT = 20
CHUNK_PAGE_MAX = 100


# ---------------------------------------------------------------------------
# GET /normalized-refs/{ref_id}/knowledge-outline
# ---------------------------------------------------------------------------


@router.get(
    "/normalized-refs/{ref_id}/knowledge-outline",
    response_model=schemas.ApiResponse[dict],
)
def get_knowledge_outline_by_ref(
    ref_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    ref = _load_ref_or_404(session, ref_id)
    _require_theory_knowledge_gate(session, ref_id)

    tree = get_outline_tree(session, ref_id)
    if tree is None:
        tree = _auto_build(session, ref=ref, request=request)
        session.commit()

    return response(_serialize_tree(tree), request)


# ---------------------------------------------------------------------------
# POST /normalized-refs/{ref_id}/knowledge-outline/rebuild
# ---------------------------------------------------------------------------


@router.post(
    "/normalized-refs/{ref_id}/knowledge-outline/rebuild",
    response_model=schemas.ApiResponse[dict],
)
def rebuild_knowledge_outline_by_ref(
    ref_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    ref = _load_ref_or_404(session, ref_id)
    _require_theory_knowledge_gate(session, ref_id)

    payload = _load_knowledge_outline_payload(ref)
    tree = build_and_persist_outline(
        session,
        ref=ref,
        payload=payload,
        rules_etag=_rules_etag(),
        trace_id=_trace_id(request),
        is_rebuild=True,
    )
    session.commit()

    return response(_serialize_tree(tree), request)


# ---------------------------------------------------------------------------
# GET /knowledge-outline-nodes/{node_id}/chunks
# ---------------------------------------------------------------------------


@router.get(
    "/knowledge-outline-nodes/{node_id}/chunks",
    response_model=schemas.ApiResponse[dict],
)
def get_knowledge_outline_node_chunks(
    node_id: str,
    request: Request,
    limit: int = Query(default=CHUNK_PAGE_DEFAULT, ge=1, le=CHUNK_PAGE_MAX),
    cursor: str | None = Query(default=None),
    session: Session = Depends(get_db),
):
    node = session.get(models.KnowledgeOutlineNode, node_id)
    if node is None:
        raise HTTPException(
            status_code=404,
            detail=f"knowledge_outline_node '{node_id}' not found",
        )

    descendant_ids = _descendant_node_ids(session, node)
    query = (
        select(models.KnowledgeChunk)
        .where(
            models.KnowledgeChunk.knowledge_outline_node_id.in_(descendant_ids),
        )
        .order_by(models.KnowledgeChunk.id.asc())
        .limit(limit + 1)
    )
    if cursor:
        query = query.where(models.KnowledgeChunk.id > cursor)

    rows = list(session.scalars(query))
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = page[-1].id if has_more else None

    return response(
        {
            "node_id": node_id,
            "chunks": [_serialize_chunk(c) for c in page],
            "next_cursor": next_cursor,
        },
        request,
    )


# ---------------------------------------------------------------------------
# GET /knowledge-outline-nodes/{node_id}/preview
# ---------------------------------------------------------------------------


@router.get(
    "/knowledge-outline-nodes/{node_id}/preview",
    response_model=schemas.ApiResponse[dict],
)
def get_knowledge_outline_node_preview(
    node_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    node = session.get(models.KnowledgeOutlineNode, node_id)
    if node is None:
        raise HTTPException(
            status_code=404,
            detail=f"knowledge_outline_node '{node_id}' not found",
        )

    descendant_ids = _descendant_node_ids(session, node)
    chunks = list(session.scalars(
        select(models.KnowledgeChunk)
        .where(
            models.KnowledgeChunk.knowledge_outline_node_id.in_(descendant_ids),
        )
        .order_by(models.KnowledgeChunk.id.asc())
        .limit(20)
    ))

    summary = _summarize_chunks(chunks, max_chars=PREVIEW_MAX_CHARS)
    return response(
        {
            "node_id": node_id,
            "title": node.title,
            "summary": summary,
            "chunk_count": len(chunks),
        },
        request,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_ref_or_404(
    session: Session, ref_id: str,
) -> models.NormalizedAssetRef:
    ref = session.get(models.NormalizedAssetRef, ref_id)
    if ref is None:
        raise HTTPException(
            status_code=404,
            detail=f"normalized_ref '{ref_id}' not found",
        )
    if ref.normalized_type != NormalizedType.DOCUMENT:
        # Non-document refs cannot have a textbook outline; return 404 to match
        # the gating semantics (no leakage of the "type" concept via 409).
        raise HTTPException(
            status_code=404,
            detail="knowledge outline requires a document-type normalized_ref",
        )
    return ref


def _require_theory_knowledge_gate(session: Session, ref_id: str) -> None:
    if not has_theory_knowledge_profile(session, ref_id):
        raise HTTPException(
            status_code=404,
            detail=(
                "knowledge outline is only available for theory_knowledge "
                "textbooks"
            ),
        )


def _auto_build(
    session: Session,
    *,
    ref: models.NormalizedAssetRef,
    request: Request,
) -> OutlineTree:
    payload = _load_knowledge_outline_payload(ref)
    return build_and_persist_outline(
        session,
        ref=ref,
        payload=payload,
        rules_etag=_rules_etag(),
        trace_id=_trace_id(request),
        is_rebuild=False,
    )


def _load_knowledge_outline_payload(
    ref: models.NormalizedAssetRef,
) -> dict[str, Any]:
    # Reuse the internal normalized payload loader — same source of truth as
    # task_outline and other document-consumption endpoints.
    from nexus_api.api.internal.normalized_refs import _load_normalized_payload

    return _load_normalized_payload(ref)


def _rules_etag() -> str | None:
    registry = get_rules_registry()
    if registry is None:
        return None
    try:
        return registry.get_rules_content_hash()
    except Exception:
        return None


def _trace_id(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def _descendant_node_ids(
    session: Session,
    node: models.KnowledgeOutlineNode,
) -> list[str]:
    """Return this node's id plus every descendant id (BFS on parent_id)."""
    rows = list(session.scalars(
        select(models.KnowledgeOutlineNode)
        .where(models.KnowledgeOutlineNode.normalized_ref_id == node.normalized_ref_id)
    ))
    children_by_parent: dict[str, list[str]] = {}
    for row in rows:
        if row.parent_id:
            children_by_parent.setdefault(row.parent_id, []).append(row.id)

    result: list[str] = [node.id]
    frontier: list[str] = [node.id]
    while frontier:
        next_frontier: list[str] = []
        for nid in frontier:
            for cid in children_by_parent.get(nid, []):
                result.append(cid)
                next_frontier.append(cid)
        frontier = next_frontier
    return result


def _summarize_chunks(
    chunks: list[models.KnowledgeChunk], *, max_chars: int,
) -> str:
    parts: list[str] = []
    running = 0
    for chunk in chunks:
        content = (chunk.content or "").strip()
        if not content:
            continue
        remaining = max_chars - running
        if remaining <= 0:
            break
        if len(content) > remaining:
            parts.append(content[:remaining] + "…")
            break
        parts.append(content)
        running += len(content) + 1  # + separator
    return " ".join(parts)


def _serialize_tree(tree: OutlineTree) -> dict[str, Any]:
    return {
        "ref_id": tree.ref_id,
        "build_run_id": tree.build_run_id,
        "total_nodes": tree.total_nodes,
        "max_depth": tree.max_depth,
        "fallback_used": tree.fallback_used,
        "root_id": tree.root_id,
        "nodes": [_serialize_node(n) for n in tree.nodes],
    }


def _serialize_node(node: OutlineNodeRead) -> dict[str, Any]:
    return {
        "id": node.id,
        "parent_id": node.parent_id,
        "level": node.level,
        "order_index": node.order_index,
        "title": node.title,
        "numbering": node.numbering,
        "numbering_path": node.numbering_path,
        "anchor_range": node.anchor_range,
        "chunk_count": node.chunk_count,
    }


def _serialize_chunk(chunk: models.KnowledgeChunk) -> dict[str, Any]:
    return {
        "id": chunk.id,
        "normalized_ref_id": chunk.normalized_ref_id,
        "knowledge_type_code": chunk.knowledge_type_code,
        "chunk_index": chunk.chunk_index,
        "content_preview": (chunk.content or "")[:200],
        "source_block_ids": chunk.source_block_ids or [],
        "knowledge_outline_node_id": chunk.knowledge_outline_node_id,
    }
