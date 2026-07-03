"""Task Outline internal read API for Console."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.responses import response
from nexus_app import models
from nexus_app.database import get_db
from nexus_app.enums import NormalizedType
from nexus_app.task_outline.orchestrator import rebuild_task_outline_for_ref
from nexus_app.task_outline.projector import DOMAIN_MODEL, DEFAULT_KNOWLEDGE_TYPE_CODE

router = APIRouter()


@router.get(
    "/normalized-refs/{ref_id}/task-outline",
    response_model=schemas.ApiResponse[dict],
)
def get_task_outline_by_ref(
    ref_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    profile = session.scalar(
        select(models.TaskOutlineProfile)
        .where(
            models.TaskOutlineProfile.normalized_ref_id == ref_id,
            models.TaskOutlineProfile.asset_profile == "course_textbook",
        )
    )
    if profile is None:
        return response(
            {
                "profile": None,
                "nodes": [],
                "chunk_projection": {
                    "projected_chunk_count": 0,
                    "stale_chunk_count": 0,
                },
            },
            request,
        )

    nodes = list(session.scalars(
        select(models.TaskOutlineNode)
        .where(models.TaskOutlineNode.profile_id == profile.id)
        .order_by(
            models.TaskOutlineNode.depth.asc(),
            models.TaskOutlineNode.order_no.asc(),
            models.TaskOutlineNode.id.asc(),
        )
    ))
    projected_count = session.scalar(
        select(func.count())
        .select_from(models.KnowledgeChunk)
        .where(
            models.KnowledgeChunk.normalized_ref_id == ref_id,
            models.KnowledgeChunk.knowledge_type_code == DEFAULT_KNOWLEDGE_TYPE_CODE,
            models.KnowledgeChunk.chunk_metadata["domain_model"].as_string() == DOMAIN_MODEL,
            models.KnowledgeChunk.chunk_metadata["task_outline_profile_id"].as_string()
            == profile.id,
        )
    ) or 0

    return response(
        {
            "profile": _serialize_profile(profile),
            "nodes": [_serialize_node(node) for node in nodes],
            "chunk_projection": {
                "projected_chunk_count": projected_count,
                "stale_chunk_count": 0,
            },
        },
        request,
    )


@router.post(
    "/normalized-refs/{ref_id}/task-outline/rebuild",
    response_model=schemas.ApiResponse[dict],
)
def rebuild_task_outline_by_ref(
    ref_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    ref = session.get(models.NormalizedAssetRef, ref_id)
    if ref is None:
        raise HTTPException(status_code=404, detail=f"normalized_ref '{ref_id}' not found")
    if ref.normalized_type != NormalizedType.DOCUMENT:
        raise HTTPException(
            status_code=409,
            detail="task outline rebuild requires a normalized document",
        )

    payload = _load_task_outline_payload(ref)
    result = rebuild_task_outline_for_ref(session, ref=ref, payload=payload)
    session.commit()

    return response(
        {
            "profile": _serialize_profile(result.profile),
            "node_count": len(result.nodes),
            "projected_chunk_count": len(result.chunks),
            "quality": result.quality,
            "index_marked_stale": result.index_marked_stale,
        },
        request,
    )


@router.get(
    "/task-outline/profiles/{profile_id}",
    response_model=schemas.ApiResponse[dict],
)
def get_task_outline_profile(
    profile_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    profile = session.get(models.TaskOutlineProfile, profile_id)
    if profile is None:
        raise HTTPException(
            status_code=404,
            detail=f"task_outline_profile '{profile_id}' not found",
        )
    return response(_serialize_profile(profile), request)


@router.get(
    "/task-outline/nodes/{node_id}",
    response_model=schemas.ApiResponse[dict],
)
def get_task_outline_node(
    node_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    node = session.get(models.TaskOutlineNode, node_id)
    if node is None:
        raise HTTPException(
            status_code=404,
            detail=f"task_outline_node '{node_id}' not found",
        )
    return response(_serialize_node(node), request)


def _load_task_outline_payload(ref: models.NormalizedAssetRef) -> dict[str, Any]:
    from nexus_api.api.internal.normalized_refs import _load_normalized_payload

    return _load_normalized_payload(ref)


def _serialize_profile(profile: models.TaskOutlineProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "normalized_ref_id": profile.normalized_ref_id,
        "asset_version_id": profile.asset_version_id,
        "asset_profile": profile.asset_profile,
        "title": profile.title,
        "textbook_subtype": profile.textbook_subtype,
        "task_profile": profile.task_profile,
        "subtype_confidence": (
            float(profile.subtype_confidence)
            if profile.subtype_confidence is not None
            else None
        ),
        "processing_profile": profile.processing_profile,
        "evidence_graph_admission": profile.evidence_graph_admission,
        "source_block_ids": profile.source_block_ids,
        "quality": profile.quality,
        "metadata": profile.profile_metadata,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


def _serialize_node(node: models.TaskOutlineNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "normalized_ref_id": node.normalized_ref_id,
        "profile_id": node.profile_id,
        "parent_id": node.parent_id,
        "node_type": node.node_type,
        "section_type": node.section_type,
        "title": node.title,
        "content": node.content,
        "summary": node.summary,
        "order_no": node.order_no,
        "depth": node.depth,
        "source_block_ids": node.source_block_ids,
        "locator": node.locator,
        "metadata": node.node_metadata,
        "created_at": node.created_at,
        "updated_at": node.updated_at,
    }
