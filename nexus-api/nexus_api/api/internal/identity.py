"""Identity endpoints (`/internal/v1/{org-units,users,api-callers}`)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.dependencies import Pagination, pagination_params, require_user
from nexus_api.responses import list_response, response
from nexus_app import auth_service, models, schemas as domain_schemas, services
from nexus_app.api_permissions import OPEN_API_FULL_ACCESS_SCOPES
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
def list_org_units(
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    rows = services.list_rows(
        session, models.OrgUnit, limit=pagination.limit, offset=pagination.offset
    )
    total = services.count_rows(session, models.OrgUnit)
    return list_response(
        rows, request,
        page=pagination.page, page_size=pagination.page_size, total=total,
    )


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
    try:
        row = services.create_user(
            session,
            payload,
            trace_id=str(getattr(request.state, "trace_id", "")),
        )
    except services.DuplicateUsernameError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return response(row, request)


@router.get("/users", response_model=schemas.ListResponse[domain_schemas.UserRead])
def list_users(
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    rows = services.list_rows(
        session, models.UserAccount, limit=pagination.limit, offset=pagination.offset
    )
    total = services.count_rows(session, models.UserAccount)
    return list_response(
        rows, request,
        page=pagination.page, page_size=pagination.page_size, total=total,
    )


@router.get("/users/{user_id}", response_model=schemas.ApiResponse[domain_schemas.UserRead])
def get_user(user_id: str, request: Request, session: Session = Depends(get_db)):
    return response(services.get_row(session, models.UserAccount, user_id, "user"), request)


@router.patch(
    "/users/{user_id}",
    response_model=schemas.ApiResponse[domain_schemas.UserRead],
)
def update_user(
    user_id: str,
    payload: domain_schemas.UserUpdate,
    request: Request,
    session: Session = Depends(get_db),
):
    """Partial update: display_name / role / org_unit_id / description / status.
    Fields omitted from the payload are left untouched."""
    try:
        row = services.update_user(
            session,
            user_id,
            payload,
            trace_id=str(getattr(request.state, "trace_id", "")),
        )
    except services.ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"user '{user_id}' not found") from exc
    return response(row, request)


@router.post(
    "/users/{user_id}/password",
    response_model=schemas.ApiResponse[domain_schemas.UserRead],
)
def reset_user_password(
    user_id: str,
    payload: domain_schemas.UserPasswordReset,
    request: Request,
    session: Session = Depends(get_db),
):
    """Admin-initiated password reset. Clears any active lockout counters."""
    try:
        row = services.reset_user_password(
            session,
            user_id,
            payload.password,
            trace_id=str(getattr(request.state, "trace_id", "")),
        )
    except services.ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"user '{user_id}' not found") from exc
    return response(row, request)


@router.post(
    "/users/me/change-password",
    response_model=schemas.ApiResponse[schemas.ChangePasswordResult],
)
def change_own_password(
    payload: schemas.ChangePasswordRequest,
    request: Request,
    session: Session = Depends(get_db),
    current_user: models.UserAccount = Depends(require_user),
):
    """Self-service password change for the currently authenticated user.

    Requires the caller to prove knowledge of the current password; on success
    re-hashes with bcrypt and clears any brute-force lockout counters.
    Rejects with 400 if the current password does not match — never leaks
    whether the account exists (the JWT already implies the account exists).
    """
    if not auth_service.verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="current password does not match")
    services.reset_user_password(
        session,
        current_user.id,
        payload.new_password,
        trace_id=str(getattr(request.state, "trace_id", "")),
        actor_type="user",
        actor_id=current_user.id,
    )
    return response(schemas.ChangePasswordResult(), request)


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
def list_api_callers(
    request: Request,
    pagination: Pagination = Depends(pagination_params),
    session: Session = Depends(get_db),
):
    rows = list(
        session.scalars(
            select(models.ApiCaller)
            .order_by(models.ApiCaller.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).all()
    )
    total = services.count_rows(session, models.ApiCaller)
    return list_response(
        rows, request,
        page=pagination.page, page_size=pagination.page_size, total=total,
    )


@router.get(
    "/api-callers/{api_caller_id}",
    response_model=schemas.ApiResponse[domain_schemas.ApiCallerRead],
)
def get_api_caller(api_caller_id: str, request: Request, session: Session = Depends(get_db)):
    return response(
        services.get_row(session, models.ApiCaller, api_caller_id, "api_caller"), request
    )


@router.patch(
    "/api-callers/{api_caller_id}",
    response_model=schemas.ApiResponse[domain_schemas.ApiCallerRead],
)
async def update_api_caller(
    api_caller_id: str,
    request: Request,
    session: Session = Depends(get_db),
):
    """Update ApiCaller expiry. Scope remains full `/open/v1/*` access."""
    caller = session.get(models.ApiCaller, api_caller_id)
    if caller is None:
        raise HTTPException(
            status_code=404, detail=f"api_caller '{api_caller_id}' not found"
        )
    if caller.revoked_at is not None:
        raise HTTPException(
            status_code=409, detail="cannot update a revoked api_caller"
        )

    body = await request.json()
    payload = domain_schemas.ApiCallerUpdate(**body)

    changed = False
    summary: dict = {"name": caller.name}

    if payload.permission_scope is not None:
        # Keep legacy PATCH clients from accidentally narrowing a credential
        # while the P0 Open API is intentionally an all-routes capability.
        caller.permission_scope = list(OPEN_API_FULL_ACCESS_SCOPES)
        summary["permission_scope"] = caller.permission_scope
        changed = True

    # Check raw body so we can distinguish "expired_at omitted" from "expired_at: null"
    if "expired_at" in body:
        caller.expired_at = payload.expired_at
        summary["expired_at"] = caller.expired_at.isoformat() if caller.expired_at else None
        changed = True

    if changed:
        write_audit(
            session,
            AuditEventType.API_CALLER_UPDATED,
            target_type="api_caller",
            target_id=caller.id,
            trace_id=str(getattr(request.state, "trace_id", "")),
            summary=summary,
        )
        session.commit()
        session.refresh(caller)
    return response(domain_schemas.ApiCallerRead.model_validate(caller), request)


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
