"""Read-only Console views over crawler-intake ``raw_jobs`` records."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.dependencies import Pagination, pagination_params
from nexus_api.responses import list_response
from nexus_app import models
from nexus_app.database import get_db

router = APIRouter()


def _serialize_raw_job(job: models.RawJob, provenance: models.RawJobProvenance | None) -> dict:
    return {
        "id": job.id,
        "job_title": job.title_raw,
        "job_responsibilities": job.responsibilities_raw or job.description_raw,
        "experience_requirement": job.experience_raw,
        "education": job.degree_raw,
        "salary_range": job.salary_raw,
        "industry": job.company_industry_raw,
        "company_name": job.company_name_raw,
        "company_size": job.company_scale_raw,
        "address": job.address_raw,
        "source_url": provenance.source_url if provenance else None,
        "collected_at": provenance.collected_at.isoformat() if provenance else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


@router.get("/raw-jobs", response_model=schemas.ListResponse[dict])
def list_raw_jobs(
    request: Request,
    q: str | None = Query(None, min_length=1, max_length=256),
    industry: str | None = Query(None, min_length=1, max_length=256),
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    """List crawler-intake jobs. Pipeline B projections are intentionally ignored."""
    stmt = select(models.RawJob, models.RawJobProvenance).outerjoin(
        models.RawJobProvenance,
        models.RawJobProvenance.raw_job_id == models.RawJob.id,
    )
    count_stmt = select(func.count(models.RawJob.id))
    clauses = []
    if q:
        pattern = f"%{q}%"
        clauses.append(
            or_(
                models.RawJob.title_raw.ilike(pattern),
                models.RawJob.company_name_raw.ilike(pattern),
                models.RawJob.description_raw.ilike(pattern),
                models.RawJob.responsibilities_raw.ilike(pattern),
            )
        )
    if industry:
        clauses.append(models.RawJob.company_industry_raw.ilike(f"%{industry}%"))
    if clauses:
        stmt = stmt.where(*clauses)
        count_stmt = count_stmt.where(*clauses)

    total = session.scalar(count_stmt) or 0
    rows = session.execute(
        stmt.order_by(models.RawJob.created_at.desc(), models.RawJob.id.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).all()
    return list_response(
        [_serialize_raw_job(job, provenance) for job, provenance in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )
