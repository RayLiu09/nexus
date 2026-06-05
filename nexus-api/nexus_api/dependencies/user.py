"""User-session JWT authentication for the `/internal/v1` router.

Token discovery order:
  1. `Authorization: Bearer <token>` header.
  2. `nexus_access_token` cookie (set by nexus-console).

Validation steps:
  - Decode and verify the JWT with the active signing key.
  - Look up the `UserAccount` row referenced by `sub`.
  - Reject disabled users with 403.

Errors map to HTTP as:
  - missing/invalid/expired token → 401
  - user disabled or no longer exists → 403
"""
from __future__ import annotations

from fastapi import Cookie, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from nexus_app import auth_service, models
from nexus_app.config import Settings, get_settings
from nexus_app.database import get_db
from nexus_app.enums import PrincipalStatus


def require_user(
    authorization: str | None = Header(None, alias="Authorization"),
    nexus_access_token: str | None = Cookie(None, alias="nexus_access_token"),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_db),
) -> models.UserAccount:
    """Resolve and validate a UserAccount from request headers/cookies.

    Raises:
        HTTPException(401) — no token, decode failure, or unknown subject
        HTTPException(403) — user disabled
    """
    token = auth_service.extract_bearer(authorization) or nexus_access_token
    if not token:
        raise HTTPException(
            status_code=401,
            detail="authentication required",
        )

    try:
        payload = auth_service.decode_access_token(settings, token)
    except auth_service.InvalidTokenError as exc:
        raise HTTPException(
            status_code=401,
            detail="invalid or expired token",
        ) from exc

    if payload.get("typ") != "access":
        raise HTTPException(status_code=401, detail="token type is not access")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="token missing subject")

    user = session.get(models.UserAccount, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="user not found")

    if user.status == PrincipalStatus.DISABLED:
        raise HTTPException(status_code=403, detail="user is disabled")

    return user
