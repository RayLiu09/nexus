"""Read-only Provider Catalog control API."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.dependencies import require_idempotency_key, require_user
from nexus_api.responses import list_response, response
from nexus_app import models, schemas as domain_schemas
from nexus_app.data_sync.catalog import list_provider_views
from nexus_app.data_sync import plans
from nexus_app.database import get_db
from nexus_app.enums import UserRole


def require_data_sync_admin(user: models.UserAccount = Depends(require_user)) -> models.UserAccount:
    if user.role != UserRole.PLATFORM_DATA_ADMIN:
        raise HTTPException(status_code=403, detail="data sync administration requires platform admin")
    return user


router = APIRouter(prefix="/data-sync", dependencies=[Depends(require_data_sync_admin)])


@router.get("/providers", response_model=schemas.ListResponse[dict])
def list_data_sync_providers(request: Request):
    items = list_provider_views()
    return list_response(items, request, page=1, page_size=max(len(items), 1), total=len(items))


@router.post("/plans", response_model=schemas.ApiResponse[domain_schemas.DataSyncPlanRead], status_code=201)
def create_data_sync_plan(
    payload: domain_schemas.DataSyncPlanCreate,
    request: Request,
    session: Session = Depends(get_db),
    user: models.UserAccount = Depends(require_data_sync_admin),
    idempotency_key: str = Depends(require_idempotency_key),
):
    try:
        plan = plans.create_plan(
            session,
            name=payload.name,
            provider_code=payload.provider_code,
            frequency=payload.frequency,
            query_config=payload.query_config,
            actor_id=user.id,
            idempotency_key=idempotency_key,
            trace_id=str(request.state.trace_id),
        )
    except plans.PlanConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except plans.PlanError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return response(domain_schemas.DataSyncPlanRead.model_validate(plan), request)


@router.get("/plans", response_model=schemas.ListResponse[domain_schemas.DataSyncPlanRead])
def list_data_sync_plans(
    request: Request,
    include_deleted: bool = Query(False),
    session: Session = Depends(get_db),
):
    items = [
        domain_schemas.DataSyncPlanRead.model_validate(plan)
        for plan in plans.list_plans(session, include_deleted=include_deleted)
    ]
    return list_response(items, request, page=1, page_size=max(len(items), 1), total=len(items))


@router.get("/plans/{plan_id}", response_model=schemas.ApiResponse[domain_schemas.DataSyncPlanRead])
def get_data_sync_plan(plan_id: str, request: Request, session: Session = Depends(get_db)):
    try:
        plan = plans.get_plan(session, plan_id)
    except plans.PlanNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return response(domain_schemas.DataSyncPlanRead.model_validate(plan), request)


def _change_plan(plan_id: str, action: str, request: Request, session: Session, user: models.UserAccount):
    try:
        plan = plans.change_plan_status(
            session, plan_id, action=action, actor_id=user.id,
            trace_id=str(request.state.trace_id),
        )
    except plans.PlanNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except plans.PlanConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return response(domain_schemas.DataSyncPlanRead.model_validate(plan), request)


@router.post("/plans/{plan_id}/pause", response_model=schemas.ApiResponse[domain_schemas.DataSyncPlanRead])
def pause_data_sync_plan(
    plan_id: str, request: Request, session: Session = Depends(get_db),
    user: models.UserAccount = Depends(require_data_sync_admin),
    _: str = Depends(require_idempotency_key),
):
    return _change_plan(plan_id, "pause", request, session, user)


@router.post("/plans/{plan_id}/resume", response_model=schemas.ApiResponse[domain_schemas.DataSyncPlanRead])
def resume_data_sync_plan(
    plan_id: str, request: Request, session: Session = Depends(get_db),
    user: models.UserAccount = Depends(require_data_sync_admin),
    _: str = Depends(require_idempotency_key),
):
    return _change_plan(plan_id, "resume", request, session, user)


@router.delete("/plans/{plan_id}", response_model=schemas.ApiResponse[domain_schemas.DataSyncPlanRead])
def delete_data_sync_plan(
    plan_id: str, request: Request, session: Session = Depends(get_db),
    user: models.UserAccount = Depends(require_data_sync_admin),
    _: str = Depends(require_idempotency_key),
):
    return _change_plan(plan_id, "delete", request, session, user)
