"""Authenticated read-only occupation reference APIs."""

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.dependencies import (
    Pagination,
    pagination_params,
    require_api_caller,
    require_user,
)
from nexus_api.responses import list_response
from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.database import get_db
from nexus_app.enums import AuditEventType
from nexus_app.reference_data.occupation_dictionary import list_records


class OccupationRead(BaseModel):
    id: str
    edition: int
    occupation_code: str
    occupation_category: str
    major_group: str
    minor_group: str | None
    occupation_name: str
    definition: str
    work_tasks: str


def make_router(prefix, auth):
    router = APIRouter(
        prefix=prefix, tags=["occupation-dictionary"], dependencies=[Depends(auth)]
    )

    @router.get("", response_model=schemas.ListResponse[OccupationRead])
    def list_occupations(
        request: Request,
        major_group: str | None = Query(None, max_length=256),
        minor_group: str | None = Query(None, max_length=256),
        occupation_name: str | None = Query(None, max_length=256),
        pagination: Pagination = Depends(pagination_params),
        actor=Depends(auth),
        session: Session = Depends(get_db),
    ):
        rows, total = list_records(
            session,
            major_group=major_group,
            minor_group=minor_group,
            occupation_name=occupation_name,
            offset=pagination.offset,
            limit=pagination.limit,
        )
        write_audit(
            session,
            AuditEventType.OPEN_RECORD_ASSETS_ACCESSED,
            "occupation_dictionary",
            "list",
            str(request.state.trace_id),
            {"result_count": total},
            actor_type="api_caller" if isinstance(actor, models.ApiCaller) else "user",
            actor_id=actor.id,
        )
        session.commit()
        return list_response(
            rows,
            request,
            page=pagination.page,
            page_size=pagination.page_size,
            total=total,
        )

    return router


internal_router = make_router("/occupation-dictionary", require_user)
business_router = make_router("/v1/occupation-dictionary", require_api_caller)
