"""Crawler plan control-plane APIs (`/internal/v1/crawler/*`)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from nexus_api import schemas as api_schemas
from nexus_api.dependencies import require_idempotency_key
from nexus_api.responses import list_response, response
from nexus_app import models, schemas as domain_schemas
from nexus_app.crawler import service as crawler_service
from nexus_app.crawler.url_safety import UnsafeCrawlerUrlError
from nexus_app.database import get_db

router = APIRouter(prefix="/crawler")


@router.get(
    "/config",
    response_model=api_schemas.ApiResponse[domain_schemas.CrawlerConfigRead],
)
def get_crawler_config(request: Request):
    try:
        payload = domain_schemas.CrawlerConfigRead(**crawler_service.read_config())
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return response(payload, request)


@router.get(
    "/regions",
    response_model=api_schemas.ListResponse[domain_schemas.CrawlerRegionRead],
)
def list_crawler_regions(request: Request):
    rows = [domain_schemas.CrawlerRegionRead(**item) for item in crawler_service.read_regions()]
    return list_response(rows, request, page=1, page_size=max(len(rows), 1), total=len(rows))


@router.get(
    "/regions/{region_code}/sites",
    response_model=api_schemas.ApiResponse[domain_schemas.CrawlerSitesRead],
)
def get_crawler_region_sites(region_code: str, request: Request):
    try:
        payload = domain_schemas.CrawlerSitesRead(**crawler_service.read_region_sites(region_code))
    except crawler_service.CrawlerPlanError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return response(payload, request)


@router.post(
    "/plans",
    response_model=api_schemas.ApiResponse[domain_schemas.CrawlerPlanRead],
    status_code=201,
    dependencies=[Depends(require_idempotency_key)],
)
def create_crawler_plan(
    payload: domain_schemas.CrawlerPlanCreate,
    request: Request,
    session: Session = Depends(get_db),
):
    try:
        row = crawler_service.create_plan(
            session,
            payload,
            trace_id=str(getattr(request.state, "trace_id", "")),
        )
    except (crawler_service.CrawlerPlanError, UnsafeCrawlerUrlError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return response(domain_schemas.CrawlerPlanRead.model_validate(row), request)


@router.get(
    "/plans",
    response_model=api_schemas.ListResponse[domain_schemas.CrawlerPlanRead],
)
def list_crawler_plans(
    request: Request,
    include_archived: bool = Query(False),
    session: Session = Depends(get_db),
):
    rows = [
        domain_schemas.CrawlerPlanRead.model_validate(row)
        for row in crawler_service.list_plans(session, include_archived=include_archived)
    ]
    return list_response(rows, request, page=1, page_size=max(len(rows), 1), total=len(rows))


@router.get(
    "/plans/{plan_id}",
    response_model=api_schemas.ApiResponse[domain_schemas.CrawlerPlanRead],
)
def get_crawler_plan(plan_id: str, request: Request, session: Session = Depends(get_db)):
    row = session.get(models.CrawlerPlan, plan_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"crawler_plan '{plan_id}' not found")
    return response(domain_schemas.CrawlerPlanRead.model_validate(row), request)


@router.post(
    "/plans/{plan_id}/archive",
    response_model=api_schemas.ApiResponse[domain_schemas.CrawlerPlanRead],
    dependencies=[Depends(require_idempotency_key)],
)
def archive_crawler_plan(
    plan_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    try:
        row = crawler_service.archive_plan(
            session,
            plan_id,
            trace_id=str(getattr(request.state, "trace_id", "")),
        )
    except crawler_service.CrawlerPlanError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return response(domain_schemas.CrawlerPlanRead.model_validate(row), request)


@router.post(
    "/plans/{plan_id}/run",
    response_model=api_schemas.ApiResponse[domain_schemas.CrawlerRunRead],
    dependencies=[Depends(require_idempotency_key)],
)
def run_crawler_plan(
    plan_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    try:
        row = crawler_service.run_plan_fake(
            session,
            plan_id,
            trace_id=str(getattr(request.state, "trace_id", "")),
        )
    except crawler_service.CrawlerPlanError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return response(domain_schemas.CrawlerRunRead.model_validate(row), request)


@router.get(
    "/runs",
    response_model=api_schemas.ListResponse[domain_schemas.CrawlerRunRead],
)
def list_crawler_runs(
    request: Request,
    plan_id: str | None = Query(None),
    session: Session = Depends(get_db),
):
    rows = [
        domain_schemas.CrawlerRunRead.model_validate(row)
        for row in crawler_service.list_runs(session, plan_id=plan_id)
    ]
    return list_response(rows, request, page=1, page_size=max(len(rows), 1), total=len(rows))


@router.get(
    "/runs/{run_id}",
    response_model=api_schemas.ApiResponse[domain_schemas.CrawlerRunRead],
)
def get_crawler_run(run_id: str, request: Request, session: Session = Depends(get_db)):
    row = session.get(models.CrawlerRun, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"crawler_run '{run_id}' not found")
    return response(domain_schemas.CrawlerRunRead.model_validate(row), request)
