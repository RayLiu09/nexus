"""Read-only Console views over crawler-intake ``raw_jobs`` records."""

from __future__ import annotations

from datetime import datetime
from tempfile import SpooledTemporaryFile

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.dependencies import Pagination, pagination_params
from nexus_api.responses import list_response
from nexus_app import models
from nexus_app.database import get_db

router = APIRouter()

_EXPORT_COLUMNS = (
    ("岗位名称", "title_raw"),
    ("岗位职责要求", "responsibilities_raw"),
    ("经验要求", "experience_raw"),
    ("学历", "degree_raw"),
    ("薪资范围", "salary_raw"),
    ("所在行业", "company_industry_raw"),
    ("公司名称", "company_name_raw"),
    ("规模", "company_scale_raw"),
    ("地址", "address_raw"),
)


def _validate_created_range(created_from: datetime | None, created_to: datetime | None) -> None:
    if any(value.tzinfo is None or value.utcoffset() is None for value in (created_from, created_to) if value):
        raise HTTPException(status_code=422, detail="created_from and created_to must include a timezone")
    if created_from and created_to and created_from > created_to:
        raise HTTPException(status_code=422, detail="created_from must not exceed created_to")


def _raw_job_filters(
    q: str | None,
    industry: str | None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
):
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
    if created_from:
        clauses.append(models.RawJob.created_at >= created_from)
    if created_to:
        clauses.append(models.RawJob.created_at <= created_to)
    return clauses


def _excel_text(value: str | None) -> str:
    text = (value or "").translate({code: None for code in range(32) if code not in (9, 10, 13)})
    if text.lstrip().startswith("="):
        text = "'" + text
    return text[:32767]


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
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    """List crawler-intake jobs. Pipeline B projections are intentionally ignored."""
    _validate_created_range(created_from, created_to)
    stmt = select(models.RawJob, models.RawJobProvenance).outerjoin(
        models.RawJobProvenance,
        models.RawJobProvenance.raw_job_id == models.RawJob.id,
    )
    count_stmt = select(func.count(models.RawJob.id))
    clauses = _raw_job_filters(q, industry, created_from, created_to)
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


@router.get("/raw-jobs/export")
def export_raw_jobs(
    q: str | None = Query(None, min_length=1, max_length=256),
    industry: str | None = Query(None, min_length=1, max_length=256),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    session: Session = Depends(get_db),
):
    """Export every matching raw job, independent of list pagination."""
    _validate_created_range(created_from, created_to)
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("岗位数据")
    sheet.append([label for label, _ in _EXPORT_COLUMNS])
    stmt = select(models.RawJob).where(
        *_raw_job_filters(q, industry, created_from, created_to)
    ).order_by(
        models.RawJob.created_at.desc(), models.RawJob.id.desc()
    )
    for job in session.scalars(stmt).yield_per(1000):
        sheet.append([
            _excel_text(job.responsibilities_raw or job.description_raw)
            if field == "responsibilities_raw" else _excel_text(getattr(job, field))
            for _, field in _EXPORT_COLUMNS
        ])
    output = SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    try:
        workbook.save(output)
        output.seek(0)
    except Exception:
        output.close()
        raise

    def chunks():
        try:
            while chunk := output.read(65536):
                yield chunk
        finally:
            output.close()

    return StreamingResponse(
        chunks(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=raw-jobs.xlsx; filename*=UTF-8''%E5%B2%97%E4%BD%8D%E6%95%B0%E6%8D%AE.xlsx",
            "Cache-Control": "no-store",
        },
    )
