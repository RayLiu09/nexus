"""API authentication dependencies.

Caller authenticates with `X-API-Key: <caller_key>` (or `Authorization: Bearer <caller_key>`).

Lookup strategy:
  1. Hash the incoming key (sha256) and look up by `caller_key_hash` — the
     supported path for server-minted callers where the plaintext is never
     stored.
  2. Fall back to a plaintext lookup against `caller_key` — covers legacy
     seed rows and pre-migration test fixtures that wrote the key directly.

Callers with `revoked_at` set or `expired_at` in the past are rejected.

P0 scope: bind protection to retrieval-facing endpoints (search, qa).
P1+: expand to other mutating endpoints; add per-call permission_scope checks.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.auth_service import hash_api_caller_key
from nexus_app.database import get_db


def _extract_key(x_api_key: str | None, authorization: str | None) -> str | None:
    if x_api_key:
        return x_api_key.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def require_api_caller(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    authorization: str | None = Header(None, alias="Authorization"),
    session: Session = Depends(get_db),
) -> models.ApiCaller:
    """Resolve and validate an ApiCaller from request headers.

    Raises:
        HTTPException(401) — no key supplied or no matching caller
        HTTPException(403) — caller expired or revoked
    """
    key = _extract_key(x_api_key, authorization)
    if not key:
        raise HTTPException(
            status_code=401,
            detail="API key required (X-API-Key header or Authorization: Bearer <key>)",
        )

    digest = hash_api_caller_key(key)
    caller = session.scalars(
        select(models.ApiCaller).where(models.ApiCaller.caller_key_hash == digest)
    ).first()
    if caller is None:
        # Legacy seed rows pre-date caller_key_hash; fall back to plaintext.
        caller = session.scalars(
            select(models.ApiCaller).where(models.ApiCaller.caller_key == key)
        ).first()
    if caller is None:
        raise HTTPException(status_code=401, detail="invalid API key")

    if caller.revoked_at is not None:
        raise HTTPException(status_code=403, detail="API key revoked")

    if caller.expired_at is not None:
        expired_at = caller.expired_at
        if expired_at.tzinfo is None:
            # SQLite drops tzinfo on roundtrip even when the column is
            # DateTime(timezone=True); treat naive values as UTC so the
            # comparison below doesn't raise TypeError.
            expired_at = expired_at.replace(tzinfo=timezone.utc)
        if expired_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=403, detail="API key expired")

    return caller
