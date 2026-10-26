"""Authenticated, read-only APIs for directly synchronized Ministry data."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.dependencies import Pagination, pagination_params, require_api_caller, require_user
from nexus_api.responses import list_response
from nexus_app import major_offerings, models
from nexus_app.audit import write_audit
from nexus_app.database import get_db
from nexus_app.enums import AuditEventType


def retired_endpoint():
    raise HTTPException(410, "专业布点旧管道接口已退役，请使用 /v1/major-offerings")


def filters(
    year: int | None = Query(None, ge=2013, le=2200),
    province_name: str | None = Query(None, max_length=128),
    province_code: str | None = Query(None, max_length=16),
    major_name: str | None = Query(None, max_length=200),
    major_code: str | None = Query(None, max_length=64),
    school_name: str | None = Query(None, max_length=256),
    school_code: str | None = Query(None, max_length=64),
):
    return {
        "year": year,
        "province_name": province_name,
        "province_code": province_code,
        "major_name": major_name,
        "major_code": major_code,
        "school_name": school_name,
        "school_code": school_code,
    }


def _read_audit(session, request, actor, total):
    write_audit(
        session,
        AuditEventType.OPEN_RECORD_ASSETS_ACCESSED,
        "major_offering_record",
        "list",
        str(request.state.trace_id),
        {"result_count": total},
        actor_type="api_caller" if isinstance(actor, models.ApiCaller) else "user",
        actor_id=actor.id,
    )
    session.commit()


def make_router(prefix, auth):
    router = APIRouter(prefix=prefix, tags=["major-offerings"], dependencies=[Depends(auth)])

    @router.get("", response_model=schemas.ListResponse[dict])
    def list_major_offerings(
        request: Request,
        criteria: dict = Depends(filters),
        pagination: Pagination = Depends(pagination_params),
        actor=Depends(auth),
        session: Session = Depends(get_db),
    ):
        rows, total = major_offerings.list_records(
            session, offset=pagination.offset, limit=pagination.limit, **criteria
        )
        _read_audit(session, request, actor, total)
        return list_response(
            rows, request, page=pagination.page, page_size=pagination.page_size, total=total
        )

    @router.get("/aggregate", response_model=schemas.ListResponse[dict])
    def aggregate_major_offerings(
        request: Request,
        criteria: dict = Depends(filters),
        group_by: list[str] = Query(["year", "province_name", "major_code", "major_name"]),
        pagination: Pagination = Depends(pagination_params),
        actor=Depends(auth),
        session: Session = Depends(get_db),
    ):
        model = models.MajorOfferingRecord
        allowed = {
            name: getattr(model, name)
            for name in ("year", "province_code", "province_name", "major_code", "major_name")
        }
        if not group_by or len(group_by) != len(set(group_by)) or set(group_by) - set(allowed):
            raise HTTPException(422, "invalid group_by")
        cols = [allowed[name] for name in group_by]
        # Name is the fallback school identity when no Ministry identifier exists.
        identity = func.coalesce(model.school_code, model.school_name_key)
        stmt = (
            major_offerings.statement(**criteria)
            .with_only_columns(
                *cols,
                func.count(model.id).label("record_count"),
                func.count(func.distinct(identity)).label("institution_count"),
            )
            .group_by(*cols)
        )
        total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = (
            session.execute(stmt.order_by(*cols).offset(pagination.offset).limit(pagination.limit))
            .mappings()
            .all()
        )
        _read_audit(session, request, actor, total)
        return list_response(
            [dict(row) for row in rows],
            request,
            page=pagination.page,
            page_size=pagination.page_size,
            total=total,
        )

    return router


internal_router = make_router("/major-offerings", require_user)
open_router = make_router("/open/v1/major-offerings", require_api_caller)
business_router = make_router("/v1/major-offerings", require_api_caller)
