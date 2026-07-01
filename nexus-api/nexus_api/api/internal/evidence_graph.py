"""`/internal/v1/knowledge-graphs/*` — Evidence Graph internal API."""

from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_api.dependencies import Pagination, pagination_params
from nexus_api.responses import list_response, response
from nexus_app import models
from nexus_app.database import get_db
from nexus_app.evidence_graph import (
    KnowledgeGraphBuildStatus,
    create_graph_build,
    get_existing_graph_build,
    get_latest_succeeded_build,
    select_graph_candidate_chunks,
)

router = APIRouter()


class GraphBuildSubmitRequest(BaseModel):
    normalized_ref_id: str = Field(min_length=1)
    graph_profile: str = Field(min_length=1)
    strategy_version: str = Field(default="evidence_kg.v1", min_length=1)
    force: bool = False
    dry_run: bool = False


@router.post("/knowledge-graphs/builds")
def submit_knowledge_graph_build(
    payload: GraphBuildSubmitRequest,
    request: Request,
    session: Session = Depends(get_db),
):
    normalized_ref = session.get(models.NormalizedAssetRef, payload.normalized_ref_id)
    if normalized_ref is None:
        raise HTTPException(status_code=404, detail="normalized_ref not found")

    selection = select_graph_candidate_chunks(
        session,
        normalized_ref_id=payload.normalized_ref_id,
        graph_profile=payload.graph_profile,
    )
    if payload.dry_run:
        return response(_selection_to_dict(selection), request)

    existing = get_existing_graph_build(
        session,
        normalized_ref_id=payload.normalized_ref_id,
        graph_profile=payload.graph_profile,
        strategy_version=payload.strategy_version,
    )
    if existing is not None and not payload.force:
        return response({
            "skipped": True,
            "reason": "build_exists",
            "build": _build_to_dict(existing),
            "candidate_selection": _selection_to_dict(selection),
        }, request)
    if existing is not None and payload.force:
        existing.status = KnowledgeGraphBuildStatus.DEPRECATED
        session.flush()
    elif existing is None:
        _deprecate_nonreusable_builds(
            session,
            normalized_ref_id=payload.normalized_ref_id,
            graph_profile=payload.graph_profile,
            strategy_version=payload.strategy_version,
        )

    try:
        build = create_graph_build(
            session,
            normalized_ref_id=payload.normalized_ref_id,
            graph_profile=payload.graph_profile,
            strategy_version=payload.strategy_version,
            source_chunk_count=selection.total_semantic_chunk_count,
            candidate_count=selection.selected_chunk_count,
            status=KnowledgeGraphBuildStatus.PENDING,
            quality_summary={
                "candidate_selection": _selection_to_dict(selection),
                "api_submit": "build_envelope_created",
            },
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = get_existing_graph_build(
            session,
            normalized_ref_id=payload.normalized_ref_id,
            graph_profile=payload.graph_profile,
            strategy_version=payload.strategy_version,
        )
        if existing is not None and not payload.force:
            return response({
                "skipped": True,
                "reason": "build_exists",
                "build": _build_to_dict(existing),
                "candidate_selection": _selection_to_dict(selection),
            }, request)
        raise
    session.refresh(build)
    return response({
        "skipped": False,
        "build": _build_to_dict(build),
        "candidate_selection": _selection_to_dict(selection),
    }, request)


@router.post("/knowledge-graphs/rebuild")
def rebuild_knowledge_graph(
    payload: GraphBuildSubmitRequest,
    request: Request,
    session: Session = Depends(get_db),
):
    return submit_knowledge_graph_build(
        GraphBuildSubmitRequest(
            normalized_ref_id=payload.normalized_ref_id,
            graph_profile=payload.graph_profile,
            strategy_version=payload.strategy_version,
            force=True if not payload.dry_run else payload.force,
            dry_run=payload.dry_run,
        ),
        request,
        session,
    )


@router.get("/knowledge-graphs/builds")
def list_knowledge_graph_builds(
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    normalized_ref_id: str | None = Query(None),
    graph_profile: str | None = Query(None),
    strategy_version: str | None = Query(None),
    status: str | None = Query(None),
    session: Session = Depends(get_db),
):
    stmt = select(models.KnowledgeGraphBuild)
    count_stmt = select(func.count()).select_from(models.KnowledgeGraphBuild)
    if normalized_ref_id:
        stmt = stmt.where(models.KnowledgeGraphBuild.normalized_ref_id == normalized_ref_id)
        count_stmt = count_stmt.where(
            models.KnowledgeGraphBuild.normalized_ref_id == normalized_ref_id
        )
    if graph_profile:
        stmt = stmt.where(models.KnowledgeGraphBuild.graph_profile == graph_profile)
        count_stmt = count_stmt.where(models.KnowledgeGraphBuild.graph_profile == graph_profile)
    if strategy_version:
        stmt = stmt.where(models.KnowledgeGraphBuild.strategy_version == strategy_version)
        count_stmt = count_stmt.where(
            models.KnowledgeGraphBuild.strategy_version == strategy_version
        )
    if status:
        stmt = stmt.where(models.KnowledgeGraphBuild.status == status)
        count_stmt = count_stmt.where(models.KnowledgeGraphBuild.status == status)
    rows = list(session.scalars(
        stmt.order_by(models.KnowledgeGraphBuild.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    ))
    total = session.scalar(count_stmt) or 0
    return list_response(
        [_build_to_dict(row) for row in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get("/knowledge-graphs/builds/{build_id}")
def get_knowledge_graph_build(
    build_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    build = session.get(models.KnowledgeGraphBuild, build_id)
    if build is None:
        raise HTTPException(status_code=404, detail="knowledge graph build not found")
    return response(_build_to_dict(build), request)


@router.get("/knowledge-graphs/builds/{build_id}/nodes")
def list_knowledge_graph_nodes(
    build_id: str,
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    node_type: str | None = Query(None),
    name: str | None = Query(None),
    session: Session = Depends(get_db),
):
    _require_build(session, build_id)
    stmt = select(models.KnowledgeGraphNode).where(
        models.KnowledgeGraphNode.graph_build_id == build_id
    )
    count_stmt = (
        select(func.count())
        .select_from(models.KnowledgeGraphNode)
        .where(models.KnowledgeGraphNode.graph_build_id == build_id)
    )
    if node_type:
        stmt = stmt.where(models.KnowledgeGraphNode.node_type == node_type)
        count_stmt = count_stmt.where(models.KnowledgeGraphNode.node_type == node_type)
    if name:
        pattern = f"%{name}%"
        stmt = stmt.where(models.KnowledgeGraphNode.name.like(pattern))
        count_stmt = count_stmt.where(models.KnowledgeGraphNode.name.like(pattern))
    rows = list(session.scalars(
        stmt.order_by(models.KnowledgeGraphNode.node_type, models.KnowledgeGraphNode.name)
        .offset(pagination.offset)
        .limit(pagination.limit)
    ))
    total = session.scalar(count_stmt) or 0
    return list_response(
        [_node_to_dict(row) for row in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get("/knowledge-graphs/builds/{build_id}/edges")
def list_knowledge_graph_edges(
    build_id: str,
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    relation_type: str | None = Query(None),
    session: Session = Depends(get_db),
):
    _require_build(session, build_id)
    stmt = select(models.KnowledgeGraphEdge).where(
        models.KnowledgeGraphEdge.graph_build_id == build_id
    )
    count_stmt = (
        select(func.count())
        .select_from(models.KnowledgeGraphEdge)
        .where(models.KnowledgeGraphEdge.graph_build_id == build_id)
    )
    if relation_type:
        stmt = stmt.where(models.KnowledgeGraphEdge.relation_type == relation_type)
        count_stmt = count_stmt.where(
            models.KnowledgeGraphEdge.relation_type == relation_type
        )
    rows = list(session.scalars(
        stmt.order_by(models.KnowledgeGraphEdge.relation_type)
        .offset(pagination.offset)
        .limit(pagination.limit)
    ))
    total = session.scalar(count_stmt) or 0
    return list_response(
        [_edge_to_dict(row) for row in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get("/knowledge-graphs/builds/{build_id}/facts")
def list_knowledge_graph_facts(
    build_id: str,
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    fact_type: str | None = Query(None),
    session: Session = Depends(get_db),
):
    _require_build(session, build_id)
    stmt = select(models.KnowledgeGraphFact).where(
        models.KnowledgeGraphFact.graph_build_id == build_id
    )
    count_stmt = (
        select(func.count())
        .select_from(models.KnowledgeGraphFact)
        .where(models.KnowledgeGraphFact.graph_build_id == build_id)
    )
    if fact_type:
        stmt = stmt.where(models.KnowledgeGraphFact.fact_type == fact_type)
        count_stmt = count_stmt.where(models.KnowledgeGraphFact.fact_type == fact_type)
    rows = list(session.scalars(
        stmt.order_by(models.KnowledgeGraphFact.fact_type, models.KnowledgeGraphFact.id)
        .offset(pagination.offset)
        .limit(pagination.limit)
    ))
    total = session.scalar(count_stmt) or 0
    return list_response(
        [_fact_to_dict(row) for row in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get("/knowledge-graphs/builds/{build_id}/evidence")
def list_knowledge_graph_evidence(
    build_id: str,
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    chunk_id: str | None = Query(None),
    fact_id: str | None = Query(None),
    edge_id: str | None = Query(None),
    entity_id: str | None = Query(None),
    session: Session = Depends(get_db),
):
    _require_build(session, build_id)
    stmt = select(models.KnowledgeGraphEvidence).where(
        models.KnowledgeGraphEvidence.graph_build_id == build_id
    )
    count_stmt = (
        select(func.count())
        .select_from(models.KnowledgeGraphEvidence)
        .where(models.KnowledgeGraphEvidence.graph_build_id == build_id)
    )
    for column, value in (
        (models.KnowledgeGraphEvidence.chunk_id, chunk_id),
        (models.KnowledgeGraphEvidence.fact_id, fact_id),
        (models.KnowledgeGraphEvidence.edge_id, edge_id),
        (models.KnowledgeGraphEvidence.entity_id, entity_id),
    ):
        if value:
            stmt = stmt.where(column == value)
            count_stmt = count_stmt.where(column == value)
    rows = list(session.scalars(
        stmt.order_by(models.KnowledgeGraphEvidence.created_at.asc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    ))
    total = session.scalar(count_stmt) or 0
    return list_response(
        [_evidence_to_dict(row) for row in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get("/normalized-refs/{ref_id}/knowledge-graph")
def get_latest_knowledge_graph_for_ref(
    ref_id: str,
    request: Request,
    graph_profile: str | None = Query(None),
    strategy_version: str | None = Query(None),
    session: Session = Depends(get_db),
):
    if session.get(models.NormalizedAssetRef, ref_id) is None:
        raise HTTPException(status_code=404, detail="normalized_ref not found")
    build = get_latest_succeeded_build(
        session,
        normalized_ref_id=ref_id,
        graph_profile=graph_profile,
        strategy_version=strategy_version,
    )
    if build is None:
        return response({"build": None}, request)
    return response({
        "build": _build_to_dict(build),
        "nodes": _count_for_build(session, models.KnowledgeGraphNode, build.id),
        "edges": _count_for_build(session, models.KnowledgeGraphEdge, build.id),
        "facts": _count_for_build(session, models.KnowledgeGraphFact, build.id),
        "evidence": _count_for_build(session, models.KnowledgeGraphEvidence, build.id),
    }, request)


def _require_build(session: Session, build_id: str) -> models.KnowledgeGraphBuild:
    build = session.get(models.KnowledgeGraphBuild, build_id)
    if build is None:
        raise HTTPException(status_code=404, detail="knowledge graph build not found")
    return build


def _deprecate_nonreusable_builds(
    session: Session,
    *,
    normalized_ref_id: str,
    graph_profile: str,
    strategy_version: str,
) -> None:
    rows = list(session.scalars(
        select(models.KnowledgeGraphBuild)
        .where(
            models.KnowledgeGraphBuild.normalized_ref_id == normalized_ref_id,
            models.KnowledgeGraphBuild.graph_type == "evidence_grounded_kg",
            models.KnowledgeGraphBuild.graph_profile == graph_profile,
            models.KnowledgeGraphBuild.strategy_version == strategy_version,
            models.KnowledgeGraphBuild.status != KnowledgeGraphBuildStatus.DEPRECATED,
            (
                models.KnowledgeGraphBuild.status == KnowledgeGraphBuildStatus.FAILED
            )
            | (
                models.KnowledgeGraphBuild.status.in_(
                    (
                        KnowledgeGraphBuildStatus.SUCCEEDED,
                        KnowledgeGraphBuildStatus.REVIEW_REQUIRED,
                    )
                )
                & (models.KnowledgeGraphBuild.node_count == 0)
                & (models.KnowledgeGraphBuild.fact_count == 0)
            ),
        )
        .with_for_update(skip_locked=True)
    ))
    for build in rows:
        summary = dict(build.quality_summary or {})
        summary["cleanup_reason"] = "nonreusable_build_deprecated_for_rebuild"
        summary["cleanup_previous_status"] = str(build.status)
        build.status = KnowledgeGraphBuildStatus.DEPRECATED
        build.quality_summary = summary
    if rows:
        session.flush()


def _count_for_build(session: Session, model, build_id: str) -> int:
    return int(session.scalar(
        select(func.count()).select_from(model).where(model.graph_build_id == build_id)
    ) or 0)


def _selection_to_dict(selection) -> dict:
    return {
        "normalized_ref_id": selection.normalized_ref_id,
        "graph_profile": selection.graph_profile,
        "selected_chunk_count": selection.selected_chunk_count,
        "skipped_chunk_count": selection.skipped_chunk_count,
        "total_semantic_chunk_count": selection.total_semantic_chunk_count,
        "by_anchor_role": selection.by_anchor_role,
        "skipped_by_reason": selection.skipped_by_reason,
    }


def _build_to_dict(b: models.KnowledgeGraphBuild) -> dict:
    return {
        "id": b.id,
        "normalized_ref_id": b.normalized_ref_id,
        "graph_type": b.graph_type,
        "graph_profile": b.graph_profile,
        "strategy_version": b.strategy_version,
        "status": b.status,
        "source_chunk_count": b.source_chunk_count,
        "candidate_count": b.candidate_count,
        "node_count": b.node_count,
        "edge_count": b.edge_count,
        "fact_count": b.fact_count,
        "quality_summary": b.quality_summary,
        "completed_at": b.completed_at,
        "error_message": b.error_message,
        "created_at": b.created_at,
        "updated_at": b.updated_at,
    }


def _node_to_dict(n: models.KnowledgeGraphNode) -> dict:
    return {
        "id": n.id,
        "graph_build_id": n.graph_build_id,
        "normalized_ref_id": n.normalized_ref_id,
        "node_key": n.node_key,
        "node_type": n.node_type,
        "name": n.name,
        "aliases": n.aliases,
        "properties": n.properties,
        "confidence": float(n.confidence) if n.confidence is not None else None,
    }


def _edge_to_dict(e: models.KnowledgeGraphEdge) -> dict:
    return {
        "id": e.id,
        "graph_build_id": e.graph_build_id,
        "normalized_ref_id": e.normalized_ref_id,
        "source_node_id": e.source_node_id,
        "relation_type": e.relation_type,
        "target_node_id": e.target_node_id,
        "properties": e.properties,
        "confidence": float(e.confidence) if e.confidence is not None else None,
    }


def _fact_to_dict(f: models.KnowledgeGraphFact) -> dict:
    return {
        "id": f.id,
        "graph_build_id": f.graph_build_id,
        "normalized_ref_id": f.normalized_ref_id,
        "fact_type": f.fact_type,
        "subject_node_id": f.subject_node_id,
        "predicate": f.predicate,
        "object_node_id": f.object_node_id,
        "object_literal": f.object_literal,
        "qualifiers": f.qualifiers,
        "confidence": float(f.confidence) if f.confidence is not None else None,
    }


def _evidence_to_dict(e: models.KnowledgeGraphEvidence) -> dict:
    return {
        "id": e.id,
        "graph_build_id": e.graph_build_id,
        "normalized_ref_id": e.normalized_ref_id,
        "fact_id": e.fact_id,
        "edge_id": e.edge_id,
        "entity_id": e.entity_id,
        "mention_id": e.mention_id,
        "chunk_id": e.chunk_id,
        "source_block_ids": e.source_block_ids,
        "locator": e.locator,
        "evidence_text": e.evidence_text,
        "extraction_method": e.extraction_method,
        "confidence": float(e.confidence) if e.confidence is not None else None,
        "created_at": e.created_at,
        "updated_at": e.updated_at,
    }
