"""Public (`/open/v1/record-assets/*`) read endpoints for Pipeline B
record-type assets.

This module owns the ability-analysis read surface frozen by
`docs/pipeline_b_b4_b6_contract_freeze.md §八.2`:

  GET /open/v1/record-assets/ability-analyses
  GET /open/v1/record-assets/ability-analyses/{analysis_id}
  GET /open/v1/record-assets/ability-analyses/{analysis_id}/tasks
  GET /open/v1/record-assets/ability-analyses/{analysis_id}/ability-items
  GET /open/v1/record-assets/ability-analyses/{analysis_id}/relations

All endpoints are read-only and require the same API-key (`require_api_caller`)
auth as the rest of `/open/v1/*`. P0 permission scope = credential auth only
(per project memory `project_p0_search_permission_scope.md`); org_scope
filtering is reserved for P1.

The job-demand read endpoints (§八.1) land in the B4 worktree's matching
module; the two routers are merged by `main.py.include_router` at boot.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.dependencies import Pagination, pagination_params, require_api_caller
from nexus_api.responses import list_response, response
from nexus_app import models
from nexus_app.database import get_db

router = APIRouter(
    prefix="/open/v1/record-assets",
    dependencies=[Depends(require_api_caller)],
    tags=["record-assets"],
)


# ---------------------------------------------------------------------------
# Serialization helpers — kept as plain dicts (not Pydantic models) so the
# response shape stays close to the schema_freeze docstrings without
# duplicating every column twice. Pydantic validation runs at the route
# decorator via `response_model=schemas.ApiResponse[dict]` style.
# ---------------------------------------------------------------------------


def _serialize_analysis(analysis: models.OccupationalAbilityAnalysis) -> dict[str, Any]:
    return {
        "id": analysis.id,
        "normalized_ref_id": analysis.normalized_ref_id,
        "asset_version_id": analysis.asset_version_id,
        "profile_id": analysis.profile_id,
        "analysis_model": analysis.analysis_model,
        "major_name": analysis.major_name,
        "major_direction": analysis.major_direction,
        "source_job_demand_dataset_id": analysis.source_job_demand_dataset_id,
        "task_count": analysis.task_count,
        "work_content_count": analysis.work_content_count,
        "ability_item_count": analysis.ability_item_count,
        "schema_version": analysis.schema_version,
        "quality_summary": analysis.quality_summary or {},
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        "updated_at": analysis.updated_at.isoformat() if analysis.updated_at else None,
    }


def _serialize_profile(profile: models.AbilityAnalysisProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "model_code": profile.model_code,
        "model_name": profile.model_name,
        "schema_version": profile.schema_version,
        "category_schema": profile.category_schema or [],
        "code_pattern": profile.code_pattern or {},
        "is_active": profile.is_active,
        "is_builtin": profile.is_builtin,
    }


def _serialize_task(
    task: models.OccupationalWorkTask,
    work_contents: list[models.OccupationalWorkContent],
) -> dict[str, Any]:
    return {
        "id": task.id,
        "task_code": task.task_code,
        "task_name": task.task_name,
        "task_description": task.task_description,
        "task_description_structured": task.task_description_structured or {},
        "display_order": task.display_order,
        "trace": task.trace or {},
        "work_contents": [_serialize_work_content(wc) for wc in work_contents],
    }


def _serialize_work_content(wc: models.OccupationalWorkContent) -> dict[str, Any]:
    return {
        "id": wc.id,
        "content_code": wc.content_code,
        "content_name": wc.content_name,
        "content_description": wc.content_description,
        "display_order": wc.display_order,
        "trace": wc.trace or {},
    }


def _serialize_ability_item(item: models.OccupationalAbilityItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "analysis_id": item.analysis_id,
        "task_id": item.task_id,
        "work_content_id": item.work_content_id,
        "ability_code": item.ability_code,
        "ability_major_category_code": item.ability_major_category_code,
        "ability_major_category_name": item.ability_major_category_name,
        "ability_sequence": item.ability_sequence,
        "ability_content": item.ability_content,
        "normalized_terms": item.normalized_terms or {},
        "confidence": float(item.confidence) if item.confidence is not None else None,
        "quality_flags": item.quality_flags or {},
        "trace": item.trace or {},
    }


def _serialize_relation(rel: models.OccupationalAbilityRelation) -> dict[str, Any]:
    return {
        "id": rel.id,
        "analysis_id": rel.analysis_id,
        "source_type": rel.source_type,
        "source_id": rel.source_id,
        "relation_type": rel.relation_type,
        "target_type": rel.target_type,
        "target_id": rel.target_id,
        "confidence": float(rel.confidence) if rel.confidence is not None else None,
        "evidence": rel.evidence or {},
    }


def _get_analysis_or_404(
    session: Session, analysis_id: str
) -> models.OccupationalAbilityAnalysis:
    analysis = session.get(models.OccupationalAbilityAnalysis, analysis_id)
    if analysis is None:
        raise HTTPException(
            status_code=404,
            detail=f"ability_analysis '{analysis_id}' not found",
        )
    return analysis


# ---------------------------------------------------------------------------
# List ability analyses
# ---------------------------------------------------------------------------


@router.get(
    "/ability-analyses",
    response_model=schemas.ListResponse[dict],
)
def list_ability_analyses(
    request: Request,
    normalized_ref_id: str | None = Query(None, max_length=36),
    profile_id: str | None = Query(None, max_length=36),
    major_name: str | None = Query(
        None,
        max_length=256,
        description=(
            "专业名称过滤，走 ILIKE substring 匹配（自 v2.0.1 起从 exact 升级为 substring，"
            "配合 §1.13 归一化的 build.major_name 命中父子专业）"
        ),
    ),
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    """Paginated list of `occupational_ability_analysis` rows.

    Filters are AND-combined; missing filters mean "no filter". Sort:
    `created_at DESC` so the latest analysis surfaces first — matches the
    console's default browse order.
    """
    stmt = select(models.OccupationalAbilityAnalysis)
    count_stmt = select(func.count(models.OccupationalAbilityAnalysis.id))
    if normalized_ref_id is not None:
        stmt = stmt.where(
            models.OccupationalAbilityAnalysis.normalized_ref_id == normalized_ref_id
        )
        count_stmt = count_stmt.where(
            models.OccupationalAbilityAnalysis.normalized_ref_id == normalized_ref_id
        )
    if profile_id is not None:
        stmt = stmt.where(models.OccupationalAbilityAnalysis.profile_id == profile_id)
        count_stmt = count_stmt.where(
            models.OccupationalAbilityAnalysis.profile_id == profile_id
        )
    if major_name is not None:
        pattern = f"%{major_name}%"
        stmt = stmt.where(models.OccupationalAbilityAnalysis.major_name.ilike(pattern))
        count_stmt = count_stmt.where(
            models.OccupationalAbilityAnalysis.major_name.ilike(pattern)
        )

    total = session.scalar(count_stmt) or 0
    rows = list(
        session.scalars(
            stmt.order_by(models.OccupationalAbilityAnalysis.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    items = [_serialize_analysis(a) for a in rows]
    return list_response(
        items,
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


# ---------------------------------------------------------------------------
# Ability analysis detail (with profile embedded)
# ---------------------------------------------------------------------------


@router.get(
    "/ability-analyses/{analysis_id}",
    response_model=schemas.ApiResponse[dict],
)
def get_ability_analysis(
    analysis_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    analysis = _get_analysis_or_404(session, analysis_id)
    profile = session.get(models.AbilityAnalysisProfile, analysis.profile_id)
    payload = {
        "analysis": _serialize_analysis(analysis),
        "profile": _serialize_profile(profile) if profile is not None else None,
    }
    return response(payload, request)


# ---------------------------------------------------------------------------
# Tasks tree (with work_contents nested)
# ---------------------------------------------------------------------------


@router.get(
    "/ability-analyses/{analysis_id}/tasks",
    response_model=schemas.ApiResponse[dict],
)
def get_ability_analysis_tasks(
    analysis_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    """Return the full task tree (tasks → work_contents) for one analysis.

    Always returned in `display_order` ascending so consumers can render
    without resorting. work_contents are batch-loaded by task_id to avoid
    an N+1 query, which matters when the analysis carries 20+ tasks (e.g.
    sample 2 has 4 tasks but a larger import may carry many more).
    """
    analysis = _get_analysis_or_404(session, analysis_id)
    tasks = list(
        session.scalars(
            select(models.OccupationalWorkTask)
            .where(models.OccupationalWorkTask.analysis_id == analysis_id)
            .order_by(
                models.OccupationalWorkTask.display_order,
                models.OccupationalWorkTask.task_code,
            )
        ).all()
    )
    work_contents = list(
        session.scalars(
            select(models.OccupationalWorkContent)
            .where(models.OccupationalWorkContent.analysis_id == analysis_id)
            .order_by(
                models.OccupationalWorkContent.task_id,
                models.OccupationalWorkContent.display_order,
                models.OccupationalWorkContent.content_code,
            )
        ).all()
    )
    by_task: dict[str, list[models.OccupationalWorkContent]] = {}
    for wc in work_contents:
        by_task.setdefault(wc.task_id, []).append(wc)

    payload = {
        "analysis_id": analysis.id,
        "analysis_model": analysis.analysis_model,
        "major_name": analysis.major_name,
        "tasks": [_serialize_task(t, by_task.get(t.id, [])) for t in tasks],
    }
    return response(payload, request)


# ---------------------------------------------------------------------------
# Ability items (paginated)
# ---------------------------------------------------------------------------


@router.get(
    "/ability-analyses/{analysis_id}/ability-items",
    response_model=schemas.ListResponse[dict],
)
def list_ability_items(
    analysis_id: str,
    request: Request,
    category: str | None = Query(
        None,
        max_length=16,
        description="Filter by ability_major_category_code (P / G / S / D ...)",
    ),
    task_code: str | None = Query(None, max_length=64),
    work_content_code: str | None = Query(None, max_length=64),
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    """Paginated ability items for an analysis with optional filters.

    `task_code` / `work_content_code` filter by the human-readable code
    (not UUID) because that's what upstream consumers see in the rendered
    tree. We resolve them to FK ids server-side.
    """
    _get_analysis_or_404(session, analysis_id)

    stmt = select(models.OccupationalAbilityItem).where(
        models.OccupationalAbilityItem.analysis_id == analysis_id
    )
    count_stmt = select(func.count(models.OccupationalAbilityItem.id)).where(
        models.OccupationalAbilityItem.analysis_id == analysis_id
    )
    if category is not None:
        stmt = stmt.where(
            models.OccupationalAbilityItem.ability_major_category_code == category
        )
        count_stmt = count_stmt.where(
            models.OccupationalAbilityItem.ability_major_category_code == category
        )
    if task_code is not None:
        task_id = session.scalar(
            select(models.OccupationalWorkTask.id).where(
                models.OccupationalWorkTask.analysis_id == analysis_id,
                models.OccupationalWorkTask.task_code == task_code,
            )
        )
        if task_id is None:
            # Unknown task_code → return empty page rather than 404 so
            # consumers can paginate without race-condition handling.
            return list_response(
                [], request,
                page=pagination.page, page_size=pagination.page_size, total=0,
            )
        stmt = stmt.where(models.OccupationalAbilityItem.task_id == task_id)
        count_stmt = count_stmt.where(
            models.OccupationalAbilityItem.task_id == task_id
        )
    if work_content_code is not None:
        wc_id = session.scalar(
            select(models.OccupationalWorkContent.id).where(
                models.OccupationalWorkContent.analysis_id == analysis_id,
                models.OccupationalWorkContent.content_code == work_content_code,
            )
        )
        if wc_id is None:
            return list_response(
                [], request,
                page=pagination.page, page_size=pagination.page_size, total=0,
            )
        stmt = stmt.where(models.OccupationalAbilityItem.work_content_id == wc_id)
        count_stmt = count_stmt.where(
            models.OccupationalAbilityItem.work_content_id == wc_id
        )

    total = session.scalar(count_stmt) or 0
    rows = list(
        session.scalars(
            stmt.order_by(
                models.OccupationalAbilityItem.ability_code,
            )
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    items = [_serialize_ability_item(it) for it in rows]
    return list_response(
        items,
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


# ---------------------------------------------------------------------------
# Relations (paginated)
# ---------------------------------------------------------------------------


@router.get(
    "/ability-analyses/{analysis_id}/relations",
    response_model=schemas.ListResponse[dict],
)
def list_ability_relations(
    analysis_id: str,
    request: Request,
    source_type: str | None = Query(None, max_length=32),
    relation_type: str | None = Query(None, max_length=64),
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    _get_analysis_or_404(session, analysis_id)
    stmt = select(models.OccupationalAbilityRelation).where(
        models.OccupationalAbilityRelation.analysis_id == analysis_id
    )
    count_stmt = select(func.count(models.OccupationalAbilityRelation.id)).where(
        models.OccupationalAbilityRelation.analysis_id == analysis_id
    )
    if source_type is not None:
        stmt = stmt.where(
            models.OccupationalAbilityRelation.source_type == source_type
        )
        count_stmt = count_stmt.where(
            models.OccupationalAbilityRelation.source_type == source_type
        )
    if relation_type is not None:
        stmt = stmt.where(
            models.OccupationalAbilityRelation.relation_type == relation_type
        )
        count_stmt = count_stmt.where(
            models.OccupationalAbilityRelation.relation_type == relation_type
        )

    total = session.scalar(count_stmt) or 0
    rows = list(
        session.scalars(
            stmt.order_by(models.OccupationalAbilityRelation.created_at)
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    items = [_serialize_relation(r) for r in rows]
    return list_response(
        items,
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


__all__ = ["router"]
