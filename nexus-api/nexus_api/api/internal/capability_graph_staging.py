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


# ---------------------------------------------------------------------------
# A1f (§10 阶段 A + §1.12 方案 B + §1.13) — one-hop by-major lookup
# ---------------------------------------------------------------------------
#
# Contract carried by four rounds of review:
# * §1.8 originally proposed a build → dataset reverse lookup — the
#   phase-A team reversed to方案 B (redundant `major_name`/`major_code`
#   on the build row) in §1.12 for simpler joins + cleaner audit.
# * §1.13 layered on normalizer reuse + double-column redundancy.
# * `build_type` enum is fixed to {teaching_standard, ability_analysis}
#   (§1.15) — job_demand goes through /record-assets/job-demand-* not
#   this endpoint.
# * at-least-one-required: caller MUST pass either `major_name` or
#   `major_code` (or both). 422 otherwise so the caller can't
#   accidentally scan every build in the table.


_BY_MAJOR_SUPPORTED_BUILD_TYPES: frozenset[str] = frozenset({
    "teaching_standard",
    "ability_analysis",
})


@router.get("/capability-graph-staging/by-major")
def get_capability_graph_by_major(
    request: Request,
    build_type: str = Query(
        ...,
        description=(
            "Build type — `teaching_standard` for the 教学标准 projection "
            "or `ability_analysis` for the 职业能力分析表 projection. "
            "`job_demand` is intentionally excluded: `job_demand` builds "
            "don't carry major columns per §1.12 决策 #4."
        ),
    ),
    major_name: str | None = Query(
        None,
        description=(
            "Substring match on `build.major_name` (case-insensitive). "
            "Provide either this or `major_code` (or both)."
        ),
    ),
    major_code: str | None = Query(
        None,
        pattern=r"^\d{4,6}$",
        description=(
            "4-6 digit major code — exact match. Provide either this or "
            "`major_name` (or both)."
        ),
    ),
    session: Session = Depends(get_db),
):
    """One-hop lookup by major_name / major_code.

    Returns the most recent GENERATED build for the given
    (major, build_type) pair, alongside every node + edge inside it —
    the Composer can render a full graph without follow-up queries.
    """
    # §1.15 build_type收敛 — anything outside the supported enum is
    # a caller mistake; report it explicitly rather than silently
    # returning empty (which would look like a data problem to Composer).
    if build_type not in _BY_MAJOR_SUPPORTED_BUILD_TYPES:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "unsupported_build_type",
                "requested": build_type,
                "supported": sorted(_BY_MAJOR_SUPPORTED_BUILD_TYPES),
            },
        )
    if major_name is None and major_code is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "at_least_one_major_required",
                "hint": "Provide `major_name`, `major_code`, or both.",
            },
        )

    # Ordering: `created_at DESC` picks the latest GENERATED build so
    # a re-run over the same normalized_ref surfaces the freshest graph.
    # Limit(1) is intentional — §1.8 explicitly rules out multi-build
    # aggregation.
    stmt = select(models.CapabilityGraphStagingBuild).where(
        models.CapabilityGraphStagingBuild.build_type == build_type,
        models.CapabilityGraphStagingBuild.status == "GENERATED",
    )
    if major_code is not None:
        stmt = stmt.where(
            models.CapabilityGraphStagingBuild.major_code == major_code,
        )
    if major_name is not None:
        stmt = stmt.where(
            models.CapabilityGraphStagingBuild.major_name.ilike(f"%{major_name}%"),
        )
    stmt = stmt.order_by(
        models.CapabilityGraphStagingBuild.created_at.desc()
    ).limit(1)
    build = session.scalar(stmt)
    if build is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "build_not_found",
                "requested": {
                    "major_name": major_name,
                    "major_code": major_code,
                    "build_type": build_type,
                },
            },
        )

    nodes = list(session.scalars(
        select(models.CapabilityGraphStagingNode)
        .where(models.CapabilityGraphStagingNode.build_id == build.id)
        .order_by(
            models.CapabilityGraphStagingNode.node_type,
            models.CapabilityGraphStagingNode.node_key,
        )
    ))
    edges = list(session.scalars(
        select(models.CapabilityGraphStagingEdge)
        .where(models.CapabilityGraphStagingEdge.build_id == build.id)
        .order_by(models.CapabilityGraphStagingEdge.edge_type)
    ))

    return response(
        {
            "build": _build_to_dict(build),
            "nodes": [_node_to_dict(n) for n in nodes],
            "edges": [_edge_to_dict(e) for e in edges],
        },
        request,
    )


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
        # A1f (§1.12 §1.13) major_name / major_code — surfaced so
        # Composer can render trace citations without a follow-up round.
        "major_name": b.major_name,
        "major_code": b.major_code,
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
