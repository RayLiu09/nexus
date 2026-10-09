"""Provider Catalog, sync plan, and run control-plane APIs."""

from datetime import datetime
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.dependencies import Pagination, pagination_params, require_idempotency_key, require_user
from nexus_api.responses import list_response, response
from nexus_app import models, schemas as domain_schemas
from nexus_app.audit import sanitize_audit_summary
from nexus_app.data_sync.catalog import list_provider_views
from nexus_app.data_sync.job_catalog import list_job_catalog
from nexus_app.data_sync import controls, plans, runs
from nexus_app.database import get_db
from nexus_app.enums import DataSyncRunStatus, UserRole


def require_data_sync_admin(user: models.UserAccount = Depends(require_user)) -> models.UserAccount:
    if user.role != UserRole.PLATFORM_DATA_ADMIN:
        raise HTTPException(status_code=403, detail="data sync administration requires platform admin")
    return user


router = APIRouter(prefix="/data-sync", dependencies=[Depends(require_data_sync_admin)])


@router.get("/providers", response_model=schemas.ListResponse[dict])
def list_data_sync_providers(request: Request):
    items = list_provider_views()
    return list_response(items, request, page=1, page_size=max(len(items), 1), total=len(items))


@router.get("/job-catalog", response_model=schemas.ListResponse[dict])
def get_job_collection_catalog(request: Request, session: Session = Depends(get_db)):
    items = list_job_catalog(session)
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


@router.post(
    "/plans/{plan_id}/runs",
    response_model=schemas.ApiResponse[domain_schemas.DataSyncRunRead],
    status_code=201,
)
def create_data_sync_run(
    plan_id: str, request: Request, session: Session = Depends(get_db),
    user: models.UserAccount = Depends(require_data_sync_admin),
    idempotency_key: str = Depends(require_idempotency_key),
):
    try:
        run = runs.create_manual_run(
            session, plan_id=plan_id, actor_id=user.id,
            idempotency_key=idempotency_key, trace_id=str(request.state.trace_id),
        )
    except runs.RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except runs.RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return response(domain_schemas.DataSyncRunRead.model_validate(run), request)


@router.get("/runs", response_model=schemas.ListResponse[domain_schemas.DataSyncRunRead])
def list_data_sync_runs(
    request: Request,
    run_id: str | None = None,
    provider_code: str | None = None,
    plan_id: str | None = None,
    status: DataSyncRunStatus | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    if any(value.tzinfo is None or value.utcoffset() is None for value in (created_from, created_to) if value):
        raise HTTPException(status_code=422, detail="created_from and created_to must include a timezone")
    if created_from and created_to and created_from > created_to:
        raise HTTPException(status_code=422, detail="created_from must not exceed created_to")
    rows, total = runs.list_runs(
        session, run_id=run_id, provider_code=provider_code, plan_id=plan_id, status=status,
        created_from=created_from, created_to=created_to,
        offset=pagination.offset, limit=pagination.limit,
    )
    return list_response(
        [domain_schemas.DataSyncRunRead.model_validate(row) for row in rows], request,
        page=pagination.page, page_size=pagination.page_size, total=total,
    )


@router.get("/runs/{run_id}", response_model=schemas.ApiResponse[domain_schemas.DataSyncRunRead])
def get_data_sync_run(run_id: str, request: Request, session: Session = Depends(get_db)):
    try:
        run = runs.get_run(session, run_id)
    except runs.RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return response(domain_schemas.DataSyncRunRead.model_validate(run), request)


_AUDIT_SUMMARY_FIELDS = frozenset({
    "action", "outcome", "error_code", "from", "to", "reason",
    "plan_id", "provider_code", "query_hash",
})


def _compact_query(value, depth: int = 0):
    if depth >= 4:
        return "...[truncated]"
    if isinstance(value, dict):
        return {key: _compact_query(item, depth + 1) for key, item in list(value.items())[:15]}
    if isinstance(value, list):
        return [_compact_query(item, depth + 1) for item in value[:5]]
    if isinstance(value, str) and len(value) > 80:
        return value[:66] + "...[truncated]"
    return value


@router.get("/runs/{run_id}/logs", response_model=schemas.ApiResponse[dict])
def get_data_sync_run_logs(
    run_id: str, request: Request,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    try:
        run = runs.get_run(session, run_id)
    except runs.RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    filters = (models.AuditLog.target_type == "data_sync_run", models.AuditLog.target_id == run_id)
    total = session.scalar(select(func.count()).select_from(models.AuditLog).where(*filters)) or 0
    rows = session.scalars(
        select(models.AuditLog).where(*filters)
        .order_by(models.AuditLog.created_at.desc(), models.AuditLog.id.desc())
        .offset(pagination.offset).limit(pagination.limit)
    )
    query_summary = json.dumps(
        _compact_query(sanitize_audit_summary(run.query_snapshot)),
        ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    )
    if len(query_summary) > 600:
        query_summary = query_summary[:586] + "...[truncated]"
    failure_summary = sanitize_audit_summary(run.failure_summary)
    if isinstance(failure_summary, str) and len(failure_summary) > 500:
        failure_summary = failure_summary[:486] + "...[truncated]"
    return response({
        "run_id": run.id,
        "plan_id": run.data_sync_config_id,
        "provider_code": run.provider_code,
        "status": run.status,
        "adapter_version": run.adapter_version,
        "query_hash": run.query_hash,
        "query_summary": query_summary,
        "external_task_id": run.external_task_id,
        "processed_count": run.processed_count,
        "success_count": run.success_count,
        "failure_count": run.failure_count,
        "skipped_count": run.skipped_count,
        "failure_summary": failure_summary,
        "last_control_action": run.last_control_action,
        "last_control_requested_at": run.last_control_requested_at,
        "last_control_operator_id": run.last_control_operator_id,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "audit_total": total,
        "audit_events": [
            {
                "id": row.id,
                "event_type": row.event_type.value,
                "actor_type": row.actor_type,
                "actor_id": row.actor_id,
                "trace_id": row.trace_id,
                "summary": {
                    key: _compact_query(sanitize_audit_summary(value))
                    for key, value in row.summary.items()
                    if key in _AUDIT_SUMMARY_FIELDS
                },
                "created_at": row.created_at,
            }
            for row in rows
        ],
    }, request)


def _control_run(
    run_id: str, action: str, request: Request, session: Session,
    user: models.UserAccount, idempotency_key: str,
):
    try:
        run = controls.control_run(
            session, run_id=run_id, action=action, actor_id=user.id,
            idempotency_key=idempotency_key, trace_id=str(request.state.trace_id),
        )
    except controls.ControlNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except controls.ControlConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except controls.ControlUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return response(domain_schemas.DataSyncRunRead.model_validate(run), request)


@router.post("/runs/{run_id}/pause", response_model=schemas.ApiResponse[domain_schemas.DataSyncRunRead])
def pause_data_sync_run(
    run_id: str, request: Request, session: Session = Depends(get_db),
    user: models.UserAccount = Depends(require_data_sync_admin),
    idempotency_key: str = Depends(require_idempotency_key),
):
    return _control_run(run_id, "pause", request, session, user, idempotency_key)


@router.post("/runs/{run_id}/resume", response_model=schemas.ApiResponse[domain_schemas.DataSyncRunRead])
def resume_data_sync_run(
    run_id: str, request: Request, session: Session = Depends(get_db),
    user: models.UserAccount = Depends(require_data_sync_admin),
    idempotency_key: str = Depends(require_idempotency_key),
):
    return _control_run(run_id, "resume", request, session, user, idempotency_key)


@router.post("/runs/{run_id}/cancel", response_model=schemas.ApiResponse[domain_schemas.DataSyncRunRead])
def cancel_data_sync_run(
    run_id: str, request: Request, session: Session = Depends(get_db),
    user: models.UserAccount = Depends(require_data_sync_admin),
    idempotency_key: str = Depends(require_idempotency_key),
):
    return _control_run(run_id, "cancel", request, session, user, idempotency_key)
