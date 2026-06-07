"""JWT user-session endpoints (`/internal/v1/auth/*`).

Hosted on a *sibling* APIRouter (`auth_router`) without the parent's
`Depends(require_user)` — these endpoints are how a client *obtains* a
token, so they must be reachable unauthenticated. Mounted directly by
`main.py` with prefix `/internal/v1/auth`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api import schemas
from nexus_api.responses import response
from nexus_app import auth_service, models
from nexus_app.audit import write_audit
from nexus_app.config import Settings, get_settings
from nexus_app.database import get_db
from nexus_app.enums import AuditEventType


def _as_utc(value: datetime) -> datetime:
    """SQLite drops tzinfo on roundtrip even when the column is
    DateTime(timezone=True); normalize naive timestamps to UTC so
    comparisons don't TypeError."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value

router = APIRouter(prefix="/internal/v1/auth")


def _auth_user_payload(
    user: models.UserAccount, settings: Settings
) -> schemas.AuthUser:
    org_name = user.org_unit.name if user.org_unit is not None else None
    return schemas.AuthUser(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        org_id=user.org_unit_id,
        org_name=org_name,
        env=settings.nexus_env,
    )


@router.post("/login", response_model=schemas.ApiResponse[schemas.TokenPair])
def auth_login(
    payload: schemas.LoginRequest,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Verify username/password and mint a short-lived access token plus a
    long-lived rotating refresh token. The refresh token is persisted as a
    `refresh_token` row so logout/refresh can revoke it server-side."""
    trace_id = str(getattr(request.state, "trace_id", ""))
    now = datetime.now(timezone.utc)

    user = session.scalars(
        select(models.UserAccount).where(models.UserAccount.username == payload.username)
    ).first()

    # Lockout precheck — refuse before doing any password work. Unknown users
    # fall through (no row to lock) so the unknown-vs-locked timing signal is
    # below brute-force noise.
    if user is not None and user.lockout_until is not None:
        lockout_until = _as_utc(user.lockout_until)
        if lockout_until > now:
            remaining = int((lockout_until - now).total_seconds()) or 1
            write_audit(
                session,
                AuditEventType.USER_LOGIN_FAILED,
                target_type="user_account",
                target_id=user.id,
                trace_id=trace_id,
                summary={"reason": "locked_out", "retry_after_seconds": remaining},
                actor_type="user",
                actor_id=user.id,
            )
            session.commit()
            raise HTTPException(
                status_code=429,
                detail=f"account is locked for {remaining}s after repeated failed logins",
                headers={"Retry-After": str(remaining)},
            )
        # Lockout window expired — clear so the counter restarts from this attempt.
        user.lockout_until = None
        user.failed_login_count = 0

    if user is None or not auth_service.verify_password(
        payload.password, user.password_hash
    ):
        summary: dict[str, object] = {"reason": "invalid_credentials"}
        # Real user → increment failure counter and lock if past threshold.
        if user is not None:
            user.failed_login_count = (user.failed_login_count or 0) + 1
            summary["failed_login_count"] = user.failed_login_count
            if user.failed_login_count >= auth_service.MAX_FAILED_LOGIN_ATTEMPTS:
                user.lockout_until = auth_service.lockout_until(now)
                summary["locked_until"] = user.lockout_until.isoformat()
                write_audit(
                    session,
                    AuditEventType.USER_LOGIN_LOCKED,
                    target_type="user_account",
                    target_id=user.id,
                    trace_id=trace_id,
                    summary={
                        "failed_login_count": user.failed_login_count,
                        "locked_until": user.lockout_until.isoformat(),
                        "lockout_window_seconds": int(
                            auth_service.LOCKOUT_DURATION.total_seconds()
                        ),
                    },
                    actor_type="user",
                    actor_id=user.id,
                )
        write_audit(
            session,
            AuditEventType.USER_LOGIN_FAILED,
            target_type="user_account",
            target_id=user.id if user is not None else payload.username,
            trace_id=trace_id,
            summary=summary,
            actor_type="user" if user is not None else None,
            actor_id=user.id if user is not None else None,
        )
        session.commit()
        raise HTTPException(status_code=401, detail="invalid username or password")

    if user.status.value != "active":
        write_audit(
            session,
            AuditEventType.USER_LOGIN_FAILED,
            target_type="user_account",
            target_id=user.id,
            trace_id=trace_id,
            summary={"reason": "user_disabled"},
            actor_type="user",
            actor_id=user.id,
        )
        session.commit()
        raise HTTPException(status_code=403, detail="user is disabled")

    # Successful login — reset the throttle window.
    if user.failed_login_count or user.lockout_until is not None:
        user.failed_login_count = 0
        user.lockout_until = None

    access_token, _ = auth_service.encode_access_token(
        settings,
        user=user,
        org_name=user.org_unit.name if user.org_unit is not None else None,
    )
    jti, _refresh_row = auth_service.issue_refresh_token(
        session, settings, user_id=user.id
    )
    refresh_token = auth_service.encode_refresh_token(
        settings, jti=jti, user_id=user.id
    )

    write_audit(
        session,
        AuditEventType.USER_LOGIN_SUCCEEDED,
        target_type="user_account",
        target_id=user.id,
        trace_id=trace_id,
        summary={"jti": jti, "username": user.username},
        actor_type="user",
        actor_id=user.id,
    )
    session.commit()

    return response(
        schemas.TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            user=_auth_user_payload(user, settings),
        ),
        request,
    )


@router.post("/refresh", response_model=schemas.ApiResponse[schemas.TokenRefresh])
def auth_refresh(
    payload: schemas.RefreshRequest,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Rotate the refresh token: verify signature, look up the jti, revoke it,
    and issue a fresh access+refresh pair. Reusing a revoked jti is logged but
    rejected — this catches replay attempts."""
    trace_id = str(getattr(request.state, "trace_id", ""))

    try:
        claims = auth_service.decode_refresh_token(settings, payload.refresh_token)
    except auth_service.InvalidTokenError as exc:
        write_audit(
            session,
            AuditEventType.TOKEN_REFRESH_FAILED,
            target_type="refresh_token",
            target_id="invalid",
            trace_id=trace_id,
            summary={"reason": "decode_failed", "detail": str(exc)[:200]},
        )
        session.commit()
        raise HTTPException(status_code=401, detail="invalid refresh token") from exc

    jti = claims.get("jti", "")
    row = auth_service.lookup_refresh_token(session, jti)
    if row is None or not auth_service.refresh_token_is_usable(row):
        write_audit(
            session,
            AuditEventType.TOKEN_REFRESH_FAILED,
            target_type="refresh_token",
            target_id=jti or "missing",
            trace_id=trace_id,
            summary={
                "reason": "revoked_or_expired_or_unknown",
                "found": row is not None,
            },
            actor_type="user",
            actor_id=claims.get("sub"),
        )
        session.commit()
        raise HTTPException(status_code=401, detail="refresh token expired or revoked")

    user = session.get(models.UserAccount, row.user_id)
    if user is None or user.status.value != "active":
        auth_service.revoke_refresh_token(row)
        session.commit()
        raise HTTPException(status_code=401, detail="user no longer active")

    auth_service.revoke_refresh_token(row)
    new_jti, _new_row = auth_service.issue_refresh_token(
        session, settings, user_id=user.id, parent_jti=jti
    )
    access_token, _ = auth_service.encode_access_token(
        settings,
        user=user,
        org_name=user.org_unit.name if user.org_unit is not None else None,
    )
    refresh_token = auth_service.encode_refresh_token(
        settings, jti=new_jti, user_id=user.id
    )

    write_audit(
        session,
        AuditEventType.TOKEN_REFRESHED,
        target_type="refresh_token",
        target_id=new_jti,
        trace_id=trace_id,
        summary={"parent_jti": jti, "username": user.username},
        actor_type="user",
        actor_id=user.id,
    )
    session.commit()

    return response(
        schemas.TokenRefresh(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
        ),
        request,
    )


@router.post("/logout", response_model=schemas.ApiResponse[schemas.LogoutResult])
def auth_logout(
    payload: schemas.LogoutRequest,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Best-effort revoke of the supplied refresh token. Always returns 200 —
    the console treats logout as terminal regardless. Idempotent."""
    trace_id = str(getattr(request.state, "trace_id", ""))

    try:
        claims = auth_service.decode_refresh_token(settings, payload.refresh_token)
    except auth_service.InvalidTokenError:
        return response(schemas.LogoutResult(ok=True), request)

    jti = claims.get("jti", "")
    row = auth_service.lookup_refresh_token(session, jti)
    if row is not None and row.revoked_at is None:
        auth_service.revoke_refresh_token(row)
        write_audit(
            session,
            AuditEventType.USER_LOGOUT,
            target_type="refresh_token",
            target_id=jti,
            trace_id=trace_id,
            summary={"user_id": row.user_id},
            actor_type="user",
            actor_id=row.user_id,
        )
        session.commit()

    return response(schemas.LogoutResult(ok=True), request)
