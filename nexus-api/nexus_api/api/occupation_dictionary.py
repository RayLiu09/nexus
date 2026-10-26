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

    @router.get("", response_model=schemas.ListResponse[OccupationRead],
                operation_id="query_occupation_dictionary" if prefix.startswith("/open/v1") else None)
    def list_occupations(
        request: Request,
        major_group: str | None = Query(None, max_length=256, description="职业大类名称或编码前缀，按字面子串匹配"),
        minor_group: str | None = Query(None, max_length=256, description="职业小类名称或编码前缀，按字面子串匹配"),
        occupation_name: str | None = Query(None, max_length=256, description="职业名称，按字面子串匹配"),
        pagination: Pagination = Depends(pagination_params),
        actor=Depends(auth),
        session: Session = Depends(get_db),
    ):
        """查询职业分类大典（2022 年版）基础表，按职业大类、小类、名称组合过滤（AND），支持分页。

        返回职业编码、职业类别、职业大类、职业小类、职业名称、职业定义和工作任务。
        数据来自本地名录及大典 PDF 核验补齐，仅表示已导入条目覆盖；不经过 AI 治理，
        不依赖资产版本或 normalized_ref，不提供编辑、删除或自动生成内容。
        """
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
open_router = make_router("/open/v1/occupation-dictionary", require_api_caller)
