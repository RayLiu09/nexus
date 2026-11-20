"""Public read-only demonstration-base records, independent of industrial parks."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, defer

from nexus_api import public_schemas as dto, schemas
from nexus_api.auth import require_api_caller
from nexus_api.dependencies import Pagination, pagination_params
from nexus_api.ecommerce_demo_bases import SOURCE_FILES, SOURCE_HOST, base_payload
from nexus_api.public_access import audit_read
from nexus_api.responses import list_response, response
from nexus_app import models
from nexus_app.database import get_db

router = APIRouter(prefix="/open/v1/ecommerce-demo-bases", tags=["public-business"],
                   dependencies=[Depends(require_api_caller)])
Level = Literal["national", "provincial"]
Batch = Literal["first", "second", "supplement"]
Group = Literal["province_code", "level", "recognized_year", "batch_code"]
BASE = models.EcommercePark
GROUP_COLUMNS = {key: getattr(BASE, key) for key in (
    "province_code", "level", "recognized_year", "batch_code",
)}


class BaseFilters(BaseModel):
    level: Level | None
    q: str | None
    province_code: str | None
    recognized_year: int | None
    batch: Batch | None


def base_filters(
    level: Level | None = Query(None, description="national=国家级，provincial=省级；省略查询两级名录，不跨级去重。"),
    q: str | None = Query(None, min_length=1, max_length=256, description="仅匹配基地名称的字面子串，不推断产业定位或地址。"),
    province_code: str | None = Query(None, pattern=r"^[0-9]{6}$", description="来源省级地区代码精确匹配，不代表基地详细地址。"),
    recognized_year: int | None = Query(None, ge=1900, le=2100, description="来源认定年份，不是入库年或网页发布时间；缺失年份不匹配。"),
    batch: Batch | None = Query(None, description="国家批次first/second/supplement；与provincial组合返回422。"),
) -> BaseFilters:
    if level == "provincial" and batch is not None:
        raise HTTPException(422, "batch is only supported for national records")
    if q is not None and not q.strip():
        raise HTTPException(422, "blank_base_query")
    return BaseFilters(level=level, q=q.strip() if q else None, province_code=province_code,
                       recognized_year=recognized_year, batch=batch)


def filter_clauses(filters: BaseFilters):
    clauses = []
    for name, column in (("level", BASE.level), ("province_code", BASE.province_code),
                         ("recognized_year", BASE.recognized_year), ("batch", BASE.batch_code)):
        value = getattr(filters, name)
        if value is not None:
            clauses.append(column == value)
    if filters.q:
        clauses.append(BASE.title.icontains(filters.q, autoescape=True))
    return clauses


def coverage(session: Session) -> dict:
    rows = session.execute(select(
        BASE.level, func.count(BASE.id), func.count(func.distinct(func.nullif(func.trim(BASE.province_code), ""))),
        func.min(BASE.created_at),
    ).group_by(BASE.level).order_by(BASE.level)).all()
    return {
        "kind": "database_snapshot", "unit": "registry_records",
        "deduplication_key": "ecommerce_parks.id", "imported_total": sum(row[1] for row in rows),
        "source_site": SOURCE_HOST,
        "source_files": [{"level": level, "filename": SOURCE_FILES[level], "record_count": count,
                          "province_count": provinces,
                          "imported_at": imported.isoformat() if imported else None}
                         for level, count, provinces, imported in rows],
        "unavailable_fields": ["operator", "detailed_address", "industry_positioning"],
        "limitations": ["ingested_snapshot_only_not_current_national_registry",
                        "cross_level_or_same_name_records_not_merged",
                        "uncollected_provinces_do_not_imply_no_bases",
                        "imported_at_is_not_source_publication_time"],
    }


@router.get("", operation_id="query_ecommerce_demo_bases",
            response_model=schemas.ListResponse[schemas.EcommerceDemoBaseRead])
def list_bases(
    request: Request, filters: BaseFilters = Depends(base_filters),
    pagination: Pagination = Depends(pagination_params),
    caller=Depends(require_api_caller), session: Session = Depends(get_db),
):
    """分页查询已入库国家级/省级电子商务示范基地，区别于产业园区。名称、地区代码、认定年和国家批次按AND过滤；省略level查询两级。返回名录事实和可用来源链接，不提供运营主体、详细地址或产业定位，不代表最新全国完整名录。"""
    clauses = filter_clauses(filters)
    total = session.scalar(select(func.count(BASE.id)).where(*clauses)) or 0
    rows = session.scalars(select(BASE).options(defer(BASE.source_payload, raiseload=True))
        .where(*clauses).order_by(BASE.level, BASE.province_code, BASE.source_order, BASE.id)
        .offset(pagination.offset).limit(pagination.limit)).all()
    items = [base_payload(row) for row in rows]
    audit_read(session, request, caller, "ecommerce_demo_bases", len(items), total=total,
               record_ids=[row.id for row in rows])
    return list_response(items, request, page=pagination.page, page_size=pagination.page_size, total=total)


@router.get("/aggregate", operation_id="aggregate_ecommerce_demo_bases",
            response_model=schemas.ListResponse[dto.EcommerceDemoBaseGroupRead])
def aggregate_bases(
    request: Request, filters: BaseFilters = Depends(base_filters),
    group_by: list[Group] = Query(default=["province_code", "level", "recognized_year"], min_length=1, max_length=4,
                                description="重复参数，维度不可重复；分组基于全量匹配名录。meta.total是组数，aggregations.matched_total是记录数。"),
    pagination: Pagination = Depends(pagination_params),
    caller=Depends(require_api_caller), session: Session = Depends(get_db),
):
    """按省级地区代码、认定级别、认定年份或国家批次汇总电子商务示范基地名录。过滤与列表相同，全量分组后分页；保留NULL组、缺失数及来源覆盖。计数单位为名录记录，不跨级或同名去重，不推断全国总量、产业定位或未收录省份不存在基地。"""
    if len(set(group_by)) != len(group_by):
        raise HTTPException(422, "duplicate_group_by")
    clauses = filter_clauses(filters)
    columns = [GROUP_COLUMNS[key] for key in group_by]
    count = func.count(BASE.id)
    grouped = select(*columns, count.label("record_count")).where(*clauses).group_by(*columns)
    total = session.scalar(select(func.count()).select_from(grouped.subquery())) or 0
    rows = session.execute(grouped.order_by(count.desc(), *(column.asc().nulls_last() for column in columns))
                           .offset(pagination.offset).limit(pagination.limit)).all()
    missing = [func.count(case((
        column.is_(None) if key == "recognized_year" else or_(column.is_(None), func.trim(column) == ""), 1,
    ))) for key, column in zip(group_by, columns)]
    counts = session.execute(select(count, *missing).where(*clauses)).one()
    aggregates = {
        "group_by": group_by, "matched_total": counts[0],
        "missing_counts": dict(zip(group_by, counts[1:])), "coverage": coverage(session),
    }
    items = [{"dimensions": dict(zip(group_by, row[:-1])), "record_count": row[-1]} for row in rows]
    audit_read(session, request, caller, "ecommerce_demo_bases_aggregate", len(items),
               total=total, matched_total=counts[0], group_by=group_by)
    return list_response(items, request, page=pagination.page, page_size=pagination.page_size,
                         total=total, aggregations=aggregates)


@router.get("/{base_id}", operation_id="get_ecommerce_demo_base",
            response_model=schemas.ApiResponse[dto.EcommerceDemoBaseDetailRead])
def get_base(base_id: str, request: Request, caller=Depends(require_api_caller), session: Session = Depends(get_db)):
    """按查询结果ID读取单条电子商务示范基地名录及来源文件/JSON定位。原站未开放链接或路径不安全时source_url为空；不返回原始JSON，不抓取网页，不虚构运营主体、详细地址或产业定位。不存在返回404。"""
    row = session.scalar(select(BASE).options(defer(BASE.source_payload, raiseload=True)).where(BASE.id == base_id))
    if row is None:
        raise HTTPException(404, "ecommerce_demo_base_not_found")
    item = {**base_payload(row), "source_file": SOURCE_FILES[row.level], "source_locator": row.source_locator}
    audit_read(session, request, caller, "ecommerce_demo_base", 1, record_id=row.id)
    return response(item, request)
