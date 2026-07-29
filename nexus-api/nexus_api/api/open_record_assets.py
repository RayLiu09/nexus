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

import hashlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.dependencies import Pagination, pagination_params, require_api_caller
from nexus_api.responses import list_response, response
from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.capability_graph.whitelists import BuildStatus, BuildType, EdgeType, NodeType
from nexus_app.database import get_db
from nexus_app.domain_normalize.administrative_division import normalize_province_name
from nexus_app.enums import AuditEventType

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


def _serialize_job_demand_record(record: models.JobDemandRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "dataset_id": record.dataset_id,
        "normalized_ref_id": record.normalized_ref_id,
        "source_record_key": record.source_record_key,
        "source_url": record.source_url,
        "source_platform": record.source_platform,
        "source_published_at": record.source_published_at.isoformat() if record.source_published_at else None,
        "job_title": record.job_title,
        "employment_type": record.employment_type,
        "job_function_category": record.job_function_category,
        "job_count": record.job_count,
        "city": record.city,
        "region": record.region,
        "salary_min": float(record.salary_min) if record.salary_min is not None else None,
        "salary_max": float(record.salary_max) if record.salary_max is not None else None,
        "salary_text": record.salary_text,
        "experience_requirement": record.experience_requirement,
        "education_requirement": record.education_requirement,
        "company_name": record.company_name,
        "company_address": record.company_address,
        "enterprise_size": record.enterprise_size,
        "industry_name": record.industry_name,
        "job_skill_text": record.job_skill_text,
        "job_description": record.job_description,
        "responsibility_text": record.responsibility_text,
        "requirement_text": record.requirement_text,
        "quality_flags": record.quality_flags or {},
        "trace": record.trace or {},
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _serialize_major_distribution_record(record: models.MajorDistributionRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "dataset_id": record.dataset_id,
        "normalized_ref_id": record.normalized_ref_id,
        "source_record_key": record.source_record_key,
        "source_row_no": record.source_row_no,
        "year": record.year,
        "year_text": record.year_text,
        "province_name": record.province_name,
        "region_scope": record.region_scope,
        "major_name": record.major_name,
        "major_code": record.major_code,
        "education_level": record.education_level,
        "distribution_count": record.distribution_count,
        "quality_flags": record.quality_flags or {},
        "trace": record.trace or {},
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _serialize_graph_node(node: models.CapabilityGraphStagingNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "node_type": node.node_type,
        "node_key": node.node_key,
        "display_name": node.display_name,
        "canonical_name": node.canonical_name,
        "properties": node.properties or {},
        "confidence": float(node.confidence) if node.confidence is not None else None,
    }


def _serialize_graph_edge(edge: models.CapabilityGraphStagingEdge) -> dict[str, Any]:
    return {
        "id": edge.id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "edge_type": edge.edge_type,
        "confidence": float(edge.confidence) if edge.confidence is not None else None,
    }


def _audit_open_record_read(
    session: Session,
    *,
    request: Request,
    caller: models.ApiCaller,
    route: str,
    result_count: int,
) -> None:
    """Persist a compact access audit without retaining caller search text."""
    trace_id = request.headers.get("x-trace-id")
    request_hash = hashlib.sha256(str(request.url.query).encode("utf-8")).hexdigest()[:16]
    write_audit(
        session,
        AuditEventType.OPEN_RECORD_ASSETS_ACCESSED,
        target_type="open_record_assets",
        target_id=trace_id or request_hash,
        trace_id=trace_id,
        actor_type="api_caller",
        actor_id=caller.id,
        summary={"route": route, "result_count": result_count, "query_hash": request_hash},
    )
    session.commit()


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


# ---------------------------------------------------------------------------
# Cross-dataset record reads
# ---------------------------------------------------------------------------


def _contains(column, value: str | None):
    return column.ilike(f"%{value.strip()}%") if value and value.strip() else None


@router.get("/job-demand-records", response_model=schemas.ListResponse[dict])
def list_job_demand_records(
    request: Request,
    job_title: str | None = Query(None, min_length=1, max_length=256),
    company_name: str | None = Query(None, min_length=1, max_length=256),
    city: str | None = Query(None, min_length=1, max_length=128),
    education: str | None = Query(None, min_length=1, max_length=128),
    industry: str | None = Query(None, min_length=1, max_length=128),
    experience: str | None = Query(None, min_length=1, max_length=128),
    pagination: Pagination = Depends(pagination_params),
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    """Search job postings across every dataset.

    Pipeline-B records are domain facts, so this route deliberately does not
    join ``asset_version`` or require an ``available`` version. ``dataset_id``
    remains a response trace field only.
    """
    clauses = [
        clause
        for clause in (
            _contains(models.JobDemandRecord.job_title, job_title),
            _contains(models.JobDemandRecord.company_name, company_name),
            _contains(models.JobDemandRecord.city, city),
            _contains(models.JobDemandRecord.education_requirement, education),
            _contains(models.JobDemandRecord.industry_name, industry),
            _contains(models.JobDemandRecord.experience_requirement, experience),
        )
        if clause is not None
    ]
    stmt = select(models.JobDemandRecord).where(*clauses)
    count_stmt = select(func.count(models.JobDemandRecord.id)).where(*clauses)
    total = session.scalar(count_stmt) or 0
    rows = list(session.scalars(
        stmt.order_by(models.JobDemandRecord.created_at.desc(), models.JobDemandRecord.id)
        .offset(pagination.offset).limit(pagination.limit)
    ).all())
    _audit_open_record_read(session, request=request, caller=caller, route="job_demand_records", result_count=total)
    return list_response(
        [_serialize_job_demand_record(row) for row in rows], request,
        page=pagination.page, page_size=pagination.page_size, total=total,
    )


def _major_distribution_filters(
    *, year: int | None, province_name: str | None, major_name: str | None,
    major_code: str | None,
) -> list:
    clauses = []
    if year is not None:
        clauses.append(models.MajorDistributionRecord.year == year)
    normalized_province = normalize_province_name(province_name)
    if normalized_province:
        clauses.append(models.MajorDistributionRecord.province_name == normalized_province)
    if major_name:
        clauses.append(models.MajorDistributionRecord.major_name.ilike(f"%{major_name.strip()}%"))
    if major_code:
        clauses.append(models.MajorDistributionRecord.major_code == major_code.strip())
    return clauses


@router.get("/major-distribution-records", response_model=schemas.ListResponse[dict])
def list_major_distribution_records(
    request: Request,
    year: int | None = Query(None, ge=1900, le=2200),
    province_name: str | None = Query(None, min_length=1, max_length=128),
    major_name: str | None = Query(None, min_length=1, max_length=256),
    major_code: str | None = Query(None, min_length=1, max_length=64),
    pagination: Pagination = Depends(pagination_params),
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    """Search professional-distribution facts across every dataset."""
    clauses = _major_distribution_filters(
        year=year, province_name=province_name, major_name=major_name, major_code=major_code,
    )
    total = session.scalar(select(func.count(models.MajorDistributionRecord.id)).where(*clauses)) or 0
    rows = list(session.scalars(
        select(models.MajorDistributionRecord).where(*clauses).order_by(
            models.MajorDistributionRecord.year.desc(),
            models.MajorDistributionRecord.major_code,
            models.MajorDistributionRecord.province_name,
            models.MajorDistributionRecord.id,
        ).offset(pagination.offset).limit(pagination.limit)
    ).all())
    _audit_open_record_read(session, request=request, caller=caller, route="major_distribution_records", result_count=total)
    return list_response(
        [_serialize_major_distribution_record(row) for row in rows], request,
        page=pagination.page, page_size=pagination.page_size, total=total,
    )


_MAJOR_DISTRIBUTION_GROUP_COLUMNS = {
    "year": models.MajorDistributionRecord.year,
    "province_name": models.MajorDistributionRecord.province_name,
    "major_name": models.MajorDistributionRecord.major_name,
    "major_code": models.MajorDistributionRecord.major_code,
}


@router.get("/major-distribution-records/aggregate", response_model=schemas.ListResponse[dict])
def aggregate_major_distribution_records(
    request: Request,
    group_by: list[str] = Query(["year", "province_name", "major_name", "major_code"]),
    year: int | None = Query(None, ge=1900, le=2200),
    province_name: str | None = Query(None, min_length=1, max_length=128),
    major_name: str | None = Query(None, min_length=1, max_length=256),
    major_code: str | None = Query(None, min_length=1, max_length=64),
    pagination: Pagination = Depends(pagination_params),
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    """Return server-side professional-distribution totals grouped by dimensions."""
    unknown = sorted(set(group_by) - set(_MAJOR_DISTRIBUTION_GROUP_COLUMNS))
    if unknown:
        raise HTTPException(status_code=422, detail={"error": "unknown_group_by", "unknown": unknown})
    if not group_by:
        raise HTTPException(status_code=422, detail={"error": "group_by_required"})
    if len(group_by) != len(set(group_by)):
        raise HTTPException(status_code=422, detail={"error": "duplicate_group_by"})

    columns = [_MAJOR_DISTRIBUTION_GROUP_COLUMNS[name] for name in group_by]
    clauses = _major_distribution_filters(
        year=year, province_name=province_name, major_name=major_name, major_code=major_code,
    )
    grouped = select(
        *columns,
        func.sum(models.MajorDistributionRecord.distribution_count).label("distribution_total"),
        func.count(models.MajorDistributionRecord.id).label("record_count"),
    ).where(*clauses).group_by(*columns)
    total = session.scalar(select(func.count()).select_from(grouped.subquery())) or 0
    rows = session.execute(
        grouped.order_by(func.sum(models.MajorDistributionRecord.distribution_count).desc(), *columns)
        .offset(pagination.offset).limit(pagination.limit)
    ).all()
    items = [
        {
            **{name: row[index] for index, name in enumerate(group_by)},
            "distribution_total": int(row.distribution_total or 0),
            "record_count": int(row.record_count),
        }
        for row in rows
    ]
    _audit_open_record_read(session, request=request, caller=caller, route="major_distribution_aggregate", result_count=total)
    return list_response(items, request, page=pagination.page, page_size=pagination.page_size, total=total)


# ---------------------------------------------------------------------------
# Public capability-graph reads. Internal staging APIs remain the operator
# surface; these adapters expose only generated graph projections.
# ---------------------------------------------------------------------------

_PUBLIC_GRAPH_NODE_CAP = 1_000
_PUBLIC_GRAPH_EDGE_CAP = 2_000


def _serialize_graph_build(build: models.CapabilityGraphStagingBuild) -> dict[str, Any]:
    return {
        "id": build.id,
        "normalized_ref_id": build.normalized_ref_id,
        "build_type": build.build_type,
        "major_name": build.major_name,
        "major_code": build.major_code,
        "schema_version": build.schema_version,
        "created_at": build.created_at.isoformat() if build.created_at else None,
    }


def _generated_graph_by_major_or_404(
    session: Session, *, build_type: str, major_name: str | None, major_code: str | None,
) -> models.CapabilityGraphStagingBuild:
    if not major_name and not major_code:
        raise HTTPException(status_code=422, detail={"error": "at_least_one_major_required"})
    stmt = select(models.CapabilityGraphStagingBuild).where(
        models.CapabilityGraphStagingBuild.build_type == build_type,
        models.CapabilityGraphStagingBuild.status == BuildStatus.GENERATED,
    )
    if major_name:
        stmt = stmt.where(models.CapabilityGraphStagingBuild.major_name.ilike(f"%{major_name.strip()}%"))
    if major_code:
        stmt = stmt.where(models.CapabilityGraphStagingBuild.major_code == major_code.strip())
    build = session.scalar(stmt.order_by(
        models.CapabilityGraphStagingBuild.created_at.desc(), models.CapabilityGraphStagingBuild.id.desc(),
    ).limit(1))
    if build is None:
        raise HTTPException(status_code=404, detail={"error": "graph_not_found", "build_type": build_type})
    return build


def _full_graph_payload(session: Session, build: models.CapabilityGraphStagingBuild) -> dict[str, Any]:
    nodes = list(session.scalars(select(models.CapabilityGraphStagingNode).where(
        models.CapabilityGraphStagingNode.build_id == build.id,
    ).order_by(models.CapabilityGraphStagingNode.node_type, models.CapabilityGraphStagingNode.node_key).limit(
        _PUBLIC_GRAPH_NODE_CAP + 1
    )).all())
    edges = list(session.scalars(select(models.CapabilityGraphStagingEdge).where(
        models.CapabilityGraphStagingEdge.build_id == build.id,
    ).order_by(models.CapabilityGraphStagingEdge.edge_type, models.CapabilityGraphStagingEdge.id).limit(
        _PUBLIC_GRAPH_EDGE_CAP + 1
    )).all())
    if len(nodes) > _PUBLIC_GRAPH_NODE_CAP or len(edges) > _PUBLIC_GRAPH_EDGE_CAP:
        raise HTTPException(status_code=413, detail={"error": "graph_response_too_large"})
    return {"build": _serialize_graph_build(build), "nodes": [_serialize_graph_node(node) for node in nodes], "edges": [_serialize_graph_edge(edge) for edge in edges]}


@router.get("/graphs/job-capability", response_model=schemas.ApiResponse[dict])
def get_job_capability_graph(
    request: Request,
    job_title: str = Query(..., min_length=1, max_length=256),
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    """Merge generated job-demand subgraphs matching a position title."""
    matches = list(session.execute(
        select(models.CapabilityGraphStagingBuild, models.CapabilityGraphStagingNode).join(
            models.CapabilityGraphStagingNode,
            models.CapabilityGraphStagingNode.build_id == models.CapabilityGraphStagingBuild.id,
        ).where(
            models.CapabilityGraphStagingBuild.build_type == BuildType.JOB_DEMAND,
            models.CapabilityGraphStagingBuild.status == BuildStatus.GENERATED,
            models.CapabilityGraphStagingNode.node_type == NodeType.JOB_ROLE,
            models.CapabilityGraphStagingNode.display_name.ilike(f"%{job_title.strip()}%"),
        ).order_by(models.CapabilityGraphStagingBuild.created_at.desc(), models.CapabilityGraphStagingBuild.id.desc())
    ).all())
    if not matches:
        raise HTTPException(status_code=404, detail={"error": "graph_not_found", "job_title": job_title})

    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    builds: list[dict[str, Any]] = []
    for build, role in matches:
        role_edges = list(session.scalars(select(models.CapabilityGraphStagingEdge).where(
            models.CapabilityGraphStagingEdge.build_id == build.id,
            models.CapabilityGraphStagingEdge.source_node_id == role.id,
            models.CapabilityGraphStagingEdge.edge_type != EdgeType.JOB_ROLE_AGGREGATES_RECORD,
        )).all())
        node_ids = {role.id, *(edge.target_node_id for edge in role_edges)}
        for node in session.scalars(select(models.CapabilityGraphStagingNode).where(
            models.CapabilityGraphStagingNode.id.in_(node_ids)
        )).all():
            nodes.setdefault(node.id, _serialize_graph_node(node))
        for edge in role_edges:
            edges.setdefault(edge.id, _serialize_graph_edge(edge))
        builds.append(_serialize_graph_build(build))
    if len(nodes) > _PUBLIC_GRAPH_NODE_CAP or len(edges) > _PUBLIC_GRAPH_EDGE_CAP:
        raise HTTPException(status_code=413, detail={"error": "graph_response_too_large"})
    _audit_open_record_read(session, request=request, caller=caller, route="job_capability_graph", result_count=len(nodes))
    return response({"job_title": job_title, "builds": builds, "nodes": list(nodes.values()), "edges": list(edges.values())}, request)


@router.get("/graphs/occupational-capability", response_model=schemas.ApiResponse[dict])
def get_occupational_capability_graph(
    request: Request,
    major_name: str | None = Query(None, min_length=1, max_length=256),
    major_code: str | None = Query(None, min_length=1, max_length=16),
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    build = _generated_graph_by_major_or_404(session, build_type=BuildType.ABILITY_ANALYSIS, major_name=major_name, major_code=major_code)
    payload = _full_graph_payload(session, build)
    _audit_open_record_read(session, request=request, caller=caller, route="occupational_capability_graph", result_count=len(payload["nodes"]))
    return response(payload, request)


@router.get("/graphs/teaching-standard-knowledge", response_model=schemas.ApiResponse[dict])
def get_teaching_standard_knowledge_graph(
    request: Request,
    major_name: str | None = Query(None, min_length=1, max_length=256),
    major_code: str | None = Query(None, min_length=1, max_length=16),
    caller: models.ApiCaller = Depends(require_api_caller),
    session: Session = Depends(get_db),
):
    build = _generated_graph_by_major_or_404(session, build_type=BuildType.TEACHING_STANDARD, major_name=major_name, major_code=major_code)
    payload = _full_graph_payload(session, build)
    _audit_open_record_read(session, request=request, caller=caller, route="teaching_standard_knowledge_graph", result_count=len(payload["nodes"]))
    return response(payload, request)


__all__ = ["router"]
