"""`/internal/v1/capability-graph-staging/*` — read-only console preview.

Surfaces B8 staging builds + their nodes + edges so the console can render
a preview before the operator decides to promote / validate / discard the
build. All endpoints are read-only at P0; promote / validate transitions
belong to a future slice once the formal graph layer ships.

Routes:
- `GET /capability-graph-staging/builds` — list builds (paginated, filter
  by normalized_ref_id / build_type / status)
- `GET /capability-graph-staging/builds/{build_id}` — build detail
- `GET /capability-graph-staging/builds/{build_id}/nodes` — node list
  (paginated, filter by node_type)
- `GET /capability-graph-staging/builds/{build_id}/edges` — edge list
  (paginated, filter by edge_type)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.dependencies import Pagination, pagination_params
from nexus_api.responses import list_response, response
from nexus_app import models
from nexus_app.database import get_db

router = APIRouter()


@router.get("/capability-graph-staging/builds")
def list_capability_graph_staging_builds(
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    normalized_ref_id: str | None = Query(None),
    build_type: str | None = Query(None),
    status: str | None = Query(None),
    session: Session = Depends(get_db),
):
    stmt = select(models.CapabilityGraphStagingBuild)
    count_stmt = select(func.count()).select_from(models.CapabilityGraphStagingBuild)
    if normalized_ref_id:
        stmt = stmt.where(
            models.CapabilityGraphStagingBuild.normalized_ref_id == normalized_ref_id
        )
        count_stmt = count_stmt.where(
            models.CapabilityGraphStagingBuild.normalized_ref_id == normalized_ref_id
        )
    if build_type:
        stmt = stmt.where(models.CapabilityGraphStagingBuild.build_type == build_type)
        count_stmt = count_stmt.where(
            models.CapabilityGraphStagingBuild.build_type == build_type
        )
    if status:
        stmt = stmt.where(models.CapabilityGraphStagingBuild.status == status)
        count_stmt = count_stmt.where(
            models.CapabilityGraphStagingBuild.status == status
        )
    stmt = (
        stmt.order_by(models.CapabilityGraphStagingBuild.created_at.desc())
        .offset(pagination.offset).limit(pagination.limit)
    )
    rows = [_build_to_dict(b) for b in session.scalars(stmt)]
    total = session.scalar(count_stmt) or 0
    return list_response(
        rows, request,
        page=pagination.page, page_size=pagination.page_size, total=total,
    )


@router.get("/capability-graph-staging/builds/{build_id}")
def get_capability_graph_staging_build(
    build_id: str, request: Request, session: Session = Depends(get_db),
):
    build = session.get(models.CapabilityGraphStagingBuild, build_id)
    if build is None:
        raise HTTPException(status_code=404, detail="staging build not found")
    return response(_build_to_dict(build), request)


@router.get("/capability-graph-staging/builds/{build_id}/nodes")
def list_capability_graph_staging_nodes(
    build_id: str,
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    node_type: str | None = Query(None),
    session: Session = Depends(get_db),
):
    # 404 guard — caller probably mistyped the id; without this we'd
    # silently return an empty list, which obscures the bug.
    if session.get(models.CapabilityGraphStagingBuild, build_id) is None:
        raise HTTPException(status_code=404, detail="staging build not found")
    stmt = select(models.CapabilityGraphStagingNode).where(
        models.CapabilityGraphStagingNode.build_id == build_id
    )
    count_stmt = (
        select(func.count())
        .select_from(models.CapabilityGraphStagingNode)
        .where(models.CapabilityGraphStagingNode.build_id == build_id)
    )
    if node_type:
        stmt = stmt.where(models.CapabilityGraphStagingNode.node_type == node_type)
        count_stmt = count_stmt.where(
            models.CapabilityGraphStagingNode.node_type == node_type
        )
    stmt = (
        stmt.order_by(models.CapabilityGraphStagingNode.node_type,
                      models.CapabilityGraphStagingNode.node_key)
        .offset(pagination.offset).limit(pagination.limit)
    )
    rows = [_node_to_dict(n) for n in session.scalars(stmt)]
    total = session.scalar(count_stmt) or 0
    return list_response(
        rows, request,
        page=pagination.page, page_size=pagination.page_size, total=total,
    )


@router.get("/capability-graph-staging/builds/{build_id}/edges")
def list_capability_graph_staging_edges(
    build_id: str,
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    edge_type: str | None = Query(None),
    session: Session = Depends(get_db),
):
    if session.get(models.CapabilityGraphStagingBuild, build_id) is None:
        raise HTTPException(status_code=404, detail="staging build not found")
    stmt = select(models.CapabilityGraphStagingEdge).where(
        models.CapabilityGraphStagingEdge.build_id == build_id
    )
    count_stmt = (
        select(func.count())
        .select_from(models.CapabilityGraphStagingEdge)
        .where(models.CapabilityGraphStagingEdge.build_id == build_id)
    )
    if edge_type:
        stmt = stmt.where(models.CapabilityGraphStagingEdge.edge_type == edge_type)
        count_stmt = count_stmt.where(
            models.CapabilityGraphStagingEdge.edge_type == edge_type
        )
    stmt = (
        stmt.order_by(models.CapabilityGraphStagingEdge.edge_type)
        .offset(pagination.offset).limit(pagination.limit)
    )
    rows = [_edge_to_dict(e) for e in session.scalars(stmt)]
    total = session.scalar(count_stmt) or 0
    return list_response(
        rows, request,
        page=pagination.page, page_size=pagination.page_size, total=total,
    )


# ---------------------------------------------------------------------------
# Row → dict adapters
# ---------------------------------------------------------------------------


def _build_to_dict(b: models.CapabilityGraphStagingBuild) -> dict:
    return {
        "id": b.id,
        "normalized_ref_id": b.normalized_ref_id,
        "domain": b.domain,
        "build_type": b.build_type,
        "status": b.status,
        "schema_version": b.schema_version,
        "quality_summary": b.quality_summary,
        "created_at": b.created_at,
        "updated_at": b.updated_at,
    }


def _node_to_dict(n: models.CapabilityGraphStagingNode) -> dict:
    return {
        "id": n.id,
        "build_id": n.build_id,
        "node_type": n.node_type,
        "node_key": n.node_key,
        "display_name": n.display_name,
        "canonical_name": n.canonical_name,
        "source_table": n.source_table,
        "source_id": n.source_id,
        "properties": n.properties,
        "confidence": float(n.confidence) if n.confidence is not None else None,
    }


def _edge_to_dict(e: models.CapabilityGraphStagingEdge) -> dict:
    return {
        "id": e.id,
        "build_id": e.build_id,
        "source_node_id": e.source_node_id,
        "target_node_id": e.target_node_id,
        "edge_type": e.edge_type,
        "source_table": e.source_table,
        "source_id": e.source_id,
        "evidence": e.evidence,
        "confidence": float(e.confidence) if e.confidence is not None else None,
    }
