"""Read-only Asset Center APIs for ecommerce demonstration bases."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.dependencies import Pagination, pagination_params
from nexus_api.responses import list_response, response
from nexus_app import models
from nexus_app.database import get_db

router = APIRouter()

Level = Literal["national", "provincial"]
Batch = Literal["first", "second", "supplement"]

_BATCH_NAMES = {
    "first": "首批",
    "second": "第二批",
    "supplement": "增补",
}
_SOURCE_HOST = "https://dzswgf.mofcom.gov.cn"
_SOURCE_FILES = {
    "national": "国家电子商务示范基地.json",
    "provincial": "省级电子商务示范基地.json",
}
_SOURCE_PATH = re.compile(r"^/news/[0-9]+/[0-9]{4}/[0-9]{1,2}/[0-9]+\.html$")


def _contains(column, value: str):
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return column.ilike(f"%{escaped}%", escape="\\")


def _filters(
    *,
    level: str,
    q: str | None,
    batch: str | None,
    province_code: str | None,
    recognized_year: int | None,
):
    if level == "provincial" and batch is not None:
        raise HTTPException(status_code=422, detail="batch is only supported for national records")
    clauses = [models.EcommercePark.level == level]
    if q:
        clauses.append(_contains(models.EcommercePark.title, q.strip()))
    if batch:
        clauses.append(models.EcommercePark.batch_code == batch)
    if province_code:
        clauses.append(models.EcommercePark.province_code == province_code)
    if recognized_year is not None:
        clauses.append(models.EcommercePark.recognized_year == recognized_year)
    return clauses


def _source_url(row: models.EcommercePark) -> str | None:
    if not row.source_link_enabled or not _SOURCE_PATH.fullmatch(row.source_path):
        return None
    return f"{_SOURCE_HOST}{row.source_path}"


def _batch_name(code: str | None) -> str | None:
    return _BATCH_NAMES.get(code) if code else None


def _payload(row: models.EcommercePark) -> dict:
    return {
        "id": row.id,
        "level": row.level,
        "title": row.title,
        "province_code": row.province_code,
        "province_name": row.province_name,
        "batch_code": row.batch_code,
        "batch_name": _batch_name(row.batch_code),
        "recognized_period": row.recognized_period,
        "recognized_year": row.recognized_year,
        "recognized_month": row.recognized_month,
        "source_publish_at": row.source_publish_at.isoformat() if row.source_publish_at else None,
        "source_order": row.source_order,
        "source_link_enabled": row.source_link_enabled,
        "source_url": _source_url(row),
    }


def _base_select(clauses: list) -> Select:
    return select(models.EcommercePark).where(*clauses)


def _coverage(session: Session, level: str) -> schemas.EcommerceDemoBaseCoverageRead:
    row_count, imported_at = session.execute(
        select(func.count(models.EcommercePark.id), func.min(models.EcommercePark.created_at)).where(
            models.EcommercePark.level == level
        )
    ).one()
    source_file = schemas.EcommerceDemoBaseSourceFileRead(
        filename=_SOURCE_FILES[level],
        coverage_kind="database_snapshot",
        source_row_count=int(row_count or 0),
        imported_at=imported_at.isoformat() if isinstance(imported_at, datetime) else None,
    )
    return schemas.EcommerceDemoBaseCoverageRead(
        imported_total=int(row_count or 0), source_files=[source_file]
    )


@router.get(
    "/ecommerce-demo-bases",
    response_model=schemas.ListResponse[schemas.EcommerceDemoBaseRead],
)
def list_ecommerce_demo_bases(
    request: Request,
    level: Level = Query(...),
    q: str | None = Query(None, min_length=1, max_length=256),
    batch: Batch | None = Query(None),
    province_code: str | None = Query(None, pattern=r"^[0-9]{6}$"),
    recognized_year: int | None = Query(None, ge=1900, le=2100),
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    clauses = _filters(
        level=level,
        q=q,
        batch=batch,
        province_code=province_code,
        recognized_year=recognized_year,
    )
    count = session.scalar(select(func.count(models.EcommercePark.id)).where(*clauses)) or 0
    if level == "national":
        ordering = (
            models.EcommercePark.province_code,
            models.EcommercePark.source_order,
            models.EcommercePark.id,
        )
    else:
        ordering = (models.EcommercePark.source_order, models.EcommercePark.id)
    rows = session.scalars(
        _base_select(clauses).order_by(*ordering).offset(pagination.offset).limit(pagination.limit)
    ).all()
    return list_response(
        [_payload(row) for row in rows],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=int(count),
    )


@router.get(
    "/ecommerce-demo-bases/aggregate",
    response_model=schemas.ApiResponse[schemas.EcommerceDemoBaseAggregateRead],
)
def aggregate_ecommerce_demo_bases(
    request: Request,
    level: Level = Query(...),
    q: str | None = Query(None, min_length=1, max_length=256),
    batch: Batch | None = Query(None),
    province_code: str | None = Query(None, pattern=r"^[0-9]{6}$"),
    recognized_year: int | None = Query(None, ge=1900, le=2100),
    session: Session = Depends(get_db),
):
    clauses = _filters(
        level=level,
        q=q,
        batch=batch,
        province_code=province_code,
        recognized_year=recognized_year,
    )
    matched_total = int(
        session.scalar(select(func.count(models.EcommercePark.id)).where(*clauses)) or 0
    )

    option_rows = session.execute(
        select(
            models.EcommercePark.batch_code,
            func.count(models.EcommercePark.id),
        )
        .where(models.EcommercePark.level == level, models.EcommercePark.batch_code.is_not(None))
        .group_by(models.EcommercePark.batch_code)
    ).all()
    province_options = session.execute(
        select(
            models.EcommercePark.province_code,
            models.EcommercePark.province_name,
            func.count(models.EcommercePark.id),
        )
        .where(
            models.EcommercePark.level == level,
            models.EcommercePark.province_code.is_not(None),
            models.EcommercePark.province_name.is_not(None),
        )
        .group_by(models.EcommercePark.province_code, models.EcommercePark.province_name)
        .order_by(models.EcommercePark.province_code)
    ).all()
    years = session.scalars(
        select(models.EcommercePark.recognized_year)
        .where(models.EcommercePark.level == level, models.EcommercePark.recognized_year.is_not(None))
        .distinct()
        .order_by(models.EcommercePark.recognized_year.desc())
    ).all()

    if level == "national":
        filtered_batch_rows = session.execute(
            select(models.EcommercePark.batch_code, func.count(models.EcommercePark.id))
            .where(*clauses, models.EcommercePark.batch_code.is_not(None))
            .group_by(models.EcommercePark.batch_code)
            .order_by(models.EcommercePark.batch_code)
        ).all()
        filtered_province_rows = session.execute(
            select(
                models.EcommercePark.province_code,
                models.EcommercePark.province_name,
                func.count(models.EcommercePark.id),
            )
            .where(*clauses, models.EcommercePark.province_code.is_not(None))
            .group_by(models.EcommercePark.province_code, models.EcommercePark.province_name)
            .order_by(models.EcommercePark.province_code)
        ).all()
        batch_counts = [
            schemas.EcommerceDemoBaseCountRead(
                code=str(code), name=_batch_name(code) or str(code), count=int(count)
            )
            for code, count in filtered_batch_rows
        ]
        province_counts = [
            schemas.EcommerceDemoBaseProvinceCountRead(
                province_code=str(code), province_name=str(name), count=int(count)
            )
            for code, name, count in filtered_province_rows
        ]
    else:
        batch_counts = []
        province_counts = []

    return response(
        schemas.EcommerceDemoBaseAggregateRead(
            matched_total=matched_total,
            batch_counts=batch_counts,
            province_counts=province_counts,
            filter_options=schemas.EcommerceDemoBaseFilterOptionsRead(
                batches=[
                    schemas.EcommerceDemoBaseCountRead(
                        code=str(code), name=_batch_name(code) or str(code), count=int(count)
                    )
                    for code, count in sorted(
                        option_rows, key=lambda item: list(_BATCH_NAMES).index(item[0])
                    )
                ]
                if level == "national"
                else [],
                provinces=[
                    schemas.EcommerceDemoBaseProvinceCountRead(
                        province_code=str(code), province_name=str(name), count=int(count)
                    )
                    for code, name, count in province_options
                ],
                recognized_years=[int(year) for year in years],
            ),
            coverage=_coverage(session, level),
        ),
        request,
    )
