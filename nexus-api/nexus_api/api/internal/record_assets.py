"""Internal console endpoints for Pipeline B record assets.

These mirror the read shape of the public `/open/v1/record-assets/*`
endpoints, but are mounted under `/internal/v1` and protected by the console
operator JWT via the parent internal router. The console must not call the
API-caller-gated `/open` surface for asset detail tabs.
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


def _serialize_job_demand_dataset(dataset: models.JobDemandDataset) -> dict:
    return {
        "id": dataset.id,
        "normalized_ref_id": dataset.normalized_ref_id,
        "asset_version_id": dataset.asset_version_id,
        "major_name": dataset.major_name,
        "industry_name": dataset.industry_name,
        "source_channel": dataset.source_channel,
        "schema_version": dataset.schema_version,
        "record_count": dataset.record_count,
        "invalid_count": dataset.invalid_count,
        "duplicate_count": dataset.duplicate_count,
        "quality_summary": dataset.quality_summary or {},
        "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
        "updated_at": dataset.updated_at.isoformat() if dataset.updated_at else None,
    }


def _serialize_job_demand_record(record: models.JobDemandRecord) -> dict:
    return {
        "id": record.id,
        "dataset_id": record.dataset_id,
        "normalized_ref_id": record.normalized_ref_id,
        "source_record_key": record.source_record_key,
        "source_url": record.source_url,
        "source_platform": record.source_platform,
        "source_published_at": (
            record.source_published_at.isoformat()
            if record.source_published_at
            else None
        ),
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


def _serialize_requirement_item(item: models.JobDemandRequirementItem) -> dict:
    return {
        "id": item.id,
        "record_id": item.record_id,
        "dataset_id": item.dataset_id,
        "item_type": item.item_type,
        "item_name": item.item_name,
        "raw_text": item.raw_text,
        "normalized_name": item.normalized_name,
        "taxonomy_code": item.taxonomy_code,
        "confidence": float(item.confidence) if item.confidence is not None else None,
        "extractor_version": item.extractor_version,
        "evidence_field": item.evidence_field,
        "ai_model_alias": item.ai_model_alias,
    }


@router.get(
    "/record-assets/job-demand-datasets",
    response_model=schemas.ListResponse[dict],
)
def list_job_demand_datasets(
    request: Request,
    normalized_ref_id: str | None = Query(None, description="Exact match"),
    major: str | None = Query(None, description="`major_name` exact match"),
    industry: str | None = Query(None, description="`industry_name` exact match"),
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    """Paginated list of B4 datasets for console-internal reads."""
    stmt = select(models.JobDemandDataset)
    count_stmt = select(func.count(models.JobDemandDataset.id))
    if normalized_ref_id is not None:
        stmt = stmt.where(models.JobDemandDataset.normalized_ref_id == normalized_ref_id)
        count_stmt = count_stmt.where(
            models.JobDemandDataset.normalized_ref_id == normalized_ref_id
        )
    if major is not None:
        stmt = stmt.where(models.JobDemandDataset.major_name == major)
        count_stmt = count_stmt.where(models.JobDemandDataset.major_name == major)
    if industry is not None:
        stmt = stmt.where(models.JobDemandDataset.industry_name == industry)
        count_stmt = count_stmt.where(models.JobDemandDataset.industry_name == industry)

    total = session.scalar(count_stmt) or 0
    rows = list(
        session.scalars(
            stmt.order_by(models.JobDemandDataset.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    return list_response(
        [_serialize_job_demand_dataset(row) for row in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get(
    "/record-assets/job-demand-datasets/{dataset_id}",
    response_model=schemas.ApiResponse[dict],
)
def get_job_demand_dataset(
    dataset_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    dataset = session.get(models.JobDemandDataset, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=404,
            detail=f"job_demand_dataset '{dataset_id}' not found",
        )
    return response(_serialize_job_demand_dataset(dataset), request)


@router.get(
    "/record-assets/job-demand-datasets/{dataset_id}/records",
    response_model=schemas.ListResponse[dict],
)
def list_job_demand_records_for_dataset(
    dataset_id: str,
    request: Request,
    city: str | None = Query(None),
    industry: str | None = Query(None, description="`industry_name` exact match"),
    enterprise_size: str | None = Query(None),
    employment_type: str | None = Query(None),
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    if session.get(models.JobDemandDataset, dataset_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"job_demand_dataset '{dataset_id}' not found",
        )

    stmt = select(models.JobDemandRecord).where(
        models.JobDemandRecord.dataset_id == dataset_id
    )
    count_stmt = select(func.count(models.JobDemandRecord.id)).where(
        models.JobDemandRecord.dataset_id == dataset_id
    )
    if city is not None:
        stmt = stmt.where(models.JobDemandRecord.city == city)
        count_stmt = count_stmt.where(models.JobDemandRecord.city == city)
    if industry is not None:
        stmt = stmt.where(models.JobDemandRecord.industry_name == industry)
        count_stmt = count_stmt.where(models.JobDemandRecord.industry_name == industry)
    if enterprise_size is not None:
        stmt = stmt.where(models.JobDemandRecord.enterprise_size == enterprise_size)
        count_stmt = count_stmt.where(
            models.JobDemandRecord.enterprise_size == enterprise_size
        )
    if employment_type is not None:
        stmt = stmt.where(models.JobDemandRecord.employment_type == employment_type)
        count_stmt = count_stmt.where(
            models.JobDemandRecord.employment_type == employment_type
        )

    total = session.scalar(count_stmt) or 0
    rows = list(
        session.scalars(
            stmt.order_by(models.JobDemandRecord.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    return list_response(
        [_serialize_job_demand_record(row) for row in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get(
    "/record-assets/job-demand-records/{record_id}",
    response_model=schemas.ApiResponse[dict],
)
def get_job_demand_record(
    record_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    record = session.get(models.JobDemandRecord, record_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"job_demand_record '{record_id}' not found",
        )
    return response(_serialize_job_demand_record(record), request)


@router.get(
    "/record-assets/job-demand-records/{record_id}/requirement-items",
    response_model=schemas.ListResponse[dict],
)
def list_requirement_items_for_record(
    record_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    if session.get(models.JobDemandRecord, record_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"job_demand_record '{record_id}' not found",
        )
    rows = list(
        session.scalars(
            select(models.JobDemandRequirementItem)
            .where(models.JobDemandRequirementItem.record_id == record_id)
            .order_by(models.JobDemandRequirementItem.created_at.asc())
        ).all()
    )
    return list_response(
        [_serialize_requirement_item(row) for row in rows],
        request,
        page=1,
        page_size=len(rows) or 1,
        total=len(rows),
    )



def _serialize_analysis(analysis: models.OccupationalAbilityAnalysis) -> dict:
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


def _serialize_profile(profile: models.AbilityAnalysisProfile) -> dict:
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


def _serialize_work_content(wc: models.OccupationalWorkContent) -> dict:
    return {
        "id": wc.id,
        "content_code": wc.content_code,
        "content_name": wc.content_name,
        "content_description": wc.content_description,
        "display_order": wc.display_order,
        "trace": wc.trace or {},
    }


def _serialize_task(
    task: models.OccupationalWorkTask,
    work_contents: list[models.OccupationalWorkContent],
) -> dict:
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


def _serialize_ability_item(item: models.OccupationalAbilityItem) -> dict:
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


@router.get(
    "/record-assets/ability-analyses",
    response_model=schemas.ListResponse[dict],
)
def list_ability_analyses(
    request: Request,
    normalized_ref_id: str | None = Query(None, max_length=36),
    profile_id: str | None = Query(None, max_length=36),
    major_name: str | None = Query(None, max_length=256),
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
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
        stmt = stmt.where(models.OccupationalAbilityAnalysis.major_name == major_name)
        count_stmt = count_stmt.where(
            models.OccupationalAbilityAnalysis.major_name == major_name
        )

    total = session.scalar(count_stmt) or 0
    rows = list(
        session.scalars(
            stmt.order_by(models.OccupationalAbilityAnalysis.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    return list_response(
        [_serialize_analysis(row) for row in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get(
    "/record-assets/ability-analyses/{analysis_id}",
    response_model=schemas.ApiResponse[dict],
)
def get_ability_analysis(
    analysis_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    analysis = _get_analysis_or_404(session, analysis_id)
    profile = session.get(models.AbilityAnalysisProfile, analysis.profile_id)
    payload = _serialize_analysis(analysis)
    payload["profile"] = _serialize_profile(profile) if profile is not None else None
    return response(payload, request)


@router.get(
    "/record-assets/ability-analyses/{analysis_id}/tasks",
    response_model=schemas.ListResponse[dict],
)
def get_ability_analysis_tasks(
    analysis_id: str,
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    _get_analysis_or_404(session, analysis_id)
    tasks = list(
        session.scalars(
            select(models.OccupationalWorkTask)
            .where(models.OccupationalWorkTask.analysis_id == analysis_id)
            .order_by(
                models.OccupationalWorkTask.display_order,
                models.OccupationalWorkTask.task_code,
            )
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    task_ids = [task.id for task in tasks]
    work_contents = []
    if task_ids:
        work_contents = list(
            session.scalars(
                select(models.OccupationalWorkContent)
                .where(models.OccupationalWorkContent.task_id.in_(task_ids))
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
    total = session.scalar(
        select(func.count(models.OccupationalWorkTask.id)).where(
            models.OccupationalWorkTask.analysis_id == analysis_id
        )
    ) or 0
    return list_response(
        [_serialize_task(task, by_task.get(task.id, [])) for task in tasks],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get(
    "/record-assets/ability-analyses/{analysis_id}/ability-items",
    response_model=schemas.ListResponse[dict],
)
def list_ability_items(
    analysis_id: str,
    request: Request,
    category: str | None = Query(None, max_length=16),
    task_code: str | None = Query(None, max_length=64),
    work_content_code: str | None = Query(None, max_length=64),
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
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
            stmt.order_by(models.OccupationalAbilityItem.ability_code)
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    return list_response(
        [_serialize_ability_item(row) for row in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )
