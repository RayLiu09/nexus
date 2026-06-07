"""AI governance run CRUD (`/internal/v1/ai/governance-runs/*`)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.api.internal._helpers import ai_gov_svc, get_rules_registry
from nexus_api.dependencies import (
    Pagination,
    pagination_params,
    require_idempotency_key,
)
from nexus_api.responses import list_response, response
from nexus_app import schemas as domain_schemas
from nexus_app.ai_governance.services import AIGovernanceError
from nexus_app.database import get_db

router = APIRouter()


@router.post(
    "/ai/governance-runs",
    response_model=schemas.ApiResponse[domain_schemas.AIGovernanceRunRead],
    status_code=201,
    dependencies=[Depends(require_idempotency_key)],
)
def create_governance_run(
    payload: domain_schemas.AIGovernanceRunCreate,
    request: Request,
    session: Session = Depends(get_db),
):
    registry = get_rules_registry()
    try:
        run = ai_gov_svc.run_governance(
            session,
            normalized_ref_id=payload.normalized_ref_id,
            profile_id=payload.profile_id,
            registry=registry,
        )
    except AIGovernanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    return response(domain_schemas.AIGovernanceRunRead.model_validate(run), request)


@router.get(
    "/ai/governance-runs",
    response_model=schemas.ListResponse[domain_schemas.AIGovernanceRunRead],
)
def list_governance_runs(
    request: Request,
    normalized_ref_id: str | None = None,
    profile_id: str | None = None,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    # In-Python slice — runs are filtered by ref/profile in the typical
    # console usage so the candidate set is small. SQL-side pagination is a
    # follow-up if the unfiltered list ever needs to scale.
    runs = ai_gov_svc.list_governance_runs(
        session, normalized_ref_id=normalized_ref_id, profile_id=profile_id
    )
    total = len(runs)
    page_slice = runs[pagination.offset : pagination.offset + pagination.limit]
    return list_response(
        [domain_schemas.AIGovernanceRunRead.model_validate(r) for r in page_slice],
        request,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get(
    "/ai/governance-runs/{run_id}",
    response_model=schemas.ApiResponse[domain_schemas.AIGovernanceRunRead],
)
def get_governance_run(
    run_id: str, request: Request, session: Session = Depends(get_db)
):
    try:
        run = ai_gov_svc.get_governance_run(session, run_id)
    except AIGovernanceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return response(domain_schemas.AIGovernanceRunRead.model_validate(run), request)


@router.get(
    "/ai/governance-runs/{run_id}/quality-summary",
    response_model=schemas.ApiResponse[dict],
)
def get_governance_run_quality_summary(
    run_id: str, request: Request, session: Session = Depends(get_db)
):
    try:
        summary = ai_gov_svc.get_quality_summary(session, run_id)
    except AIGovernanceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if summary is None:
        raise HTTPException(status_code=404, detail="No quality summary available for this run")
    return response(summary, request)
