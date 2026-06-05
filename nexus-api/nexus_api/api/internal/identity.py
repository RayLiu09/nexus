"""Identity endpoints (`/internal/v1/{org-units,users,api-callers}`)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.responses import list_response, response
from nexus_app import models, schemas as domain_schemas, services
from nexus_app.audit import write_audit
from nexus_app.database import get_db
from nexus_app.enums import AuditEventType

router = APIRouter()


# ── Org units ────────────────────────────────────────────────────────────


@router.post(
    "/org-units",
    response_model=schemas.ApiResponse[domain_schemas.OrgUnitRead],
    status_code=201,
)
def create_org_unit(
    payload: domain_schemas.OrgUnitCreate, request: Request, session: Session = Depends(get_db)
):
    return response(services.create_org_unit(session, payload), request)


@router.get("/org-units", response_model=schemas.ListResponse[domain_schemas.OrgUnitRead])
def list_org_units(request: Request, session: Session = Depends(get_db)):
    return list_response(services.list_rows(session, models.OrgUnit), request)


@router.get(
    "/org-units/{org_unit_id}",
    response_model=schemas.ApiResponse[domain_schemas.OrgUnitRead],
)
def get_org_unit(org_unit_id: str, request: Request, session: Session = Depends(get_db)):
    return response(services.get_row(session, models.OrgUnit, org_unit_id, "org_unit"), request)


# ── Users ────────────────────────────────────────────────────────────────


@router.post(
    "/users",
    response_model=schemas.ApiResponse[domain_schemas.UserRead],
    status_code=201,
)
def create_user(
    payload: domain_schemas.UserCreate, request: Request, session: Session = Depends(get_db)
):
    return response(services.create_user(session, payload), request)


@router.get("/users", response_model=schemas.ListResponse[domain_schemas.UserRead])
def list_users(request: Request, session: Session = Depends(get_db)):
    return list_response(services.list_rows(session, models.UserAccount), request)


@router.get("/users/{user_id}", response_model=schemas.ApiResponse[domain_schemas.UserRead])
def get_user(user_id: str, request: Request, session: Session = Depends(get_db)):
    return response(services.get_row(session, models.UserAccount, user_id, "user"), request)


# ── API callers ──────────────────────────────────────────────────────────


@router.post(
    "/api-callers",
    response_model=schemas.ApiResponse[domain_schemas.ApiCallerMintRead],
    status_code=201,
)
def create_api_caller(
    payload: domain_schemas.ApiCallerCreate, request: Request, session: Session = Depends(get_db)
):
    """Mint a new ApiCaller. If `caller_key` is omitted (recommended), the
    server generates a high-entropy key, stores only its sha256 hash, and
    returns the plaintext in `caller_key_plaintext` exactly once. The console
    must surface this to the operator and they must save it; subsequent reads
    return `caller_key_plaintext=null`."""
    result = services.mint_api_caller(
        session,
        payload,
        trace_id=str(getattr(request.state, "trace_id", "")),
    )
    read = domain_schemas.ApiCallerMintRead.model_validate(result.caller)
    if result.caller_key_plaintext is not None:
        read = read.model_copy(
            update={"caller_key_plaintext": result.caller_key_plaintext}
        )
    return response(read, request)


@router.get("/api-callers", response_model=schemas.ListResponse[domain_schemas.ApiCallerRead])
def list_api_callers(request: Request, session: Session = Depends(get_db)):
    rows = list(
        session.scalars(
            select(models.ApiCaller).order_by(models.ApiCaller.created_at.desc())
        ).all()
    )
    return list_response(rows, request)


@router.get(
    "/api-callers/{api_caller_id}",
    response_model=schemas.ApiResponse[domain_schemas.ApiCallerRead],
)
def get_api_caller(api_caller_id: str, request: Request, session: Session = Depends(get_db)):
    return response(
        services.get_row(session, models.ApiCaller, api_caller_id, "api_caller"), request
    )


@router.delete(
    "/api-callers/{api_caller_id}",
    response_model=schemas.ApiResponse[domain_schemas.ApiCallerRead],
)
def revoke_api_caller(
    api_caller_id: str, request: Request, session: Session = Depends(get_db)
):
    """Soft-revoke: mark `revoked_at`, leaving the row intact for audit. Future
    auth attempts fail with 403. Idempotent — re-deleting a revoked caller
    returns the existing row unchanged."""
    caller = session.get(models.ApiCaller, api_caller_id)
    if caller is None:
        raise HTTPException(
            status_code=404, detail=f"api_caller '{api_caller_id}' not found"
        )
    if caller.revoked_at is None:
        caller.revoked_at = datetime.now(timezone.utc)
        write_audit(
            session,
            AuditEventType.API_CALLER_REVOKED,
            target_type="api_caller",
            target_id=caller.id,
            trace_id=str(getattr(request.state, "trace_id", "")),
            summary={"name": caller.name},
        )
        session.commit()
        session.refresh(caller)
    return response(domain_schemas.ApiCallerRead.model_validate(caller), request)
