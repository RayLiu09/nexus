"""Auth primitives shared between nexus-api routes and admin tooling.

Covers four concerns:

1. Password hashing (bcrypt) for `UserAccount.password_hash`.
2. API-caller key minting and hashing (sha256 of a server-generated secret).
3. JWT access-token encode/decode (HS256 by default).
4. Refresh-token persistence: issue, lookup, revoke, rotate against the
   `refresh_token` table.

The module deliberately keeps no module-level mutable state so it can be safely
imported into FastAPI request handlers and worker code alike.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.config import Settings

# ── Brute-force lockout knobs ────────────────────────────────────────────

# How many consecutive failed logins put a user_account into lockout.
MAX_FAILED_LOGIN_ATTEMPTS: int = 5

# How long the account stays locked after the threshold is hit. The window
# is intentionally short — long enough to slow brute force to one-per-minutes,
# short enough not to weaponize the lockout into a DoS against legitimate
# users by an adversary spamming wrong passwords.
LOCKOUT_DURATION: timedelta = timedelta(minutes=15)


def lockout_until(now: datetime) -> datetime:
    """Compute when a freshly-locked account should reopen."""
    return now + LOCKOUT_DURATION


# ── Password hashing ─────────────────────────────────────────────────────


def hash_password(plain: str) -> str:
    """Return a bcrypt hash suitable for `UserAccount.password_hash`."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str | None) -> bool:
    """Constant-time check; returns False for any unparseable hash."""
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ── Header helpers ───────────────────────────────────────────────────────


def extract_bearer(authorization: str | None) -> str | None:
    """Return the token from `Authorization: Bearer <token>` or None."""
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


_ACCESS_COOKIE_NAME = "nexus_access_token"


def extract_access_token_from_cookie(cookie_header: str | None) -> str | None:
    """Return the access token from a raw `Cookie` header, or None.

    Matches the `nexus_access_token` cookie set by nexus-console
    (`nexus-console/lib/auth/session.ts`).
    """
    if not cookie_header:
        return None
    for chunk in cookie_header.split(";"):
        name, _, value = chunk.strip().partition("=")
        if name == _ACCESS_COOKIE_NAME and value:
            return value
    return None


# ── API caller key ───────────────────────────────────────────────────────

# A 32-byte URL-safe random string (~43 chars). Prefixed `nx_` for log greppability.
_CALLER_KEY_PREFIX = "nx_"


def generate_api_caller_key() -> str:
    """Mint a high-entropy caller key. Returned ONCE to the operator; only the
    sha256 digest is persisted."""
    return _CALLER_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_caller_key(key: str) -> str:
    """Stable hash used for both storage and lookup."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


# ── JWT access token ─────────────────────────────────────────────────────

# Fallback secret generated once per process. Re-using `secrets.token_urlsafe`
# guarantees tokens issued under the fallback cannot be verified by another
# process — which is exactly what we want for dev/test isolation.
_DEV_FALLBACK_SECRET: str | None = None


def _effective_jwt_secret(settings: Settings) -> str:
    global _DEV_FALLBACK_SECRET
    if settings.jwt_secret:
        return settings.jwt_secret
    if _DEV_FALLBACK_SECRET is None:
        _DEV_FALLBACK_SECRET = secrets.token_urlsafe(48)
    return _DEV_FALLBACK_SECRET


def encode_access_token(
    settings: Settings,
    *,
    user: models.UserAccount,
    org_name: str | None,
) -> tuple[str, datetime]:
    """Encode a short-lived access token. Returns (token, expires_at).

    Payload mirrors the fields the console expects (see
    `nexus-console/lib/auth/token.ts::JwtPayload`).
    """
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=settings.jwt_access_ttl_seconds)
    payload: dict[str, Any] = {
        "sub": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "org_id": user.org_unit_id,
        "org_name": org_name,
        "env": settings.nexus_env,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "iss": settings.jwt_issuer,
        "typ": "access",
    }
    token = jwt.encode(
        payload, _effective_jwt_secret(settings), algorithm=settings.jwt_algorithm
    )
    return token, exp


class InvalidTokenError(Exception):
    """Wraps any decode/verify failure into a single exception type for the
    auth dependency to translate to HTTP 401."""


def decode_access_token(settings: Settings, token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            _effective_jwt_secret(settings),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc


# ── Refresh tokens ───────────────────────────────────────────────────────


def _new_jti() -> str:
    return secrets.token_urlsafe(32)


def issue_refresh_token(
    session: Session,
    settings: Settings,
    *,
    user_id: str,
    parent_jti: str | None = None,
) -> tuple[str, models.RefreshToken]:
    """Persist a fresh `refresh_token` row and return (jti, row).

    The caller is responsible for emitting the opaque token string to the
    client. We only persist the jti — the JWT layer does the rest.
    """
    now = datetime.now(timezone.utc)
    jti = _new_jti()
    row = models.RefreshToken(
        jti=jti,
        user_id=user_id,
        issued_at=now,
        expires_at=now + timedelta(seconds=settings.jwt_refresh_ttl_seconds),
        parent_jti=parent_jti,
    )
    session.add(row)
    session.flush()
    return jti, row


def encode_refresh_token(settings: Settings, *, jti: str, user_id: str) -> str:
    """Wrap the refresh jti in a JWT so it has the same shape as access tokens
    (and so we can detect tampering before hitting the DB)."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=settings.jwt_refresh_ttl_seconds)
    payload = {
        "sub": user_id,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "iss": settings.jwt_issuer,
        "typ": "refresh",
    }
    return jwt.encode(
        payload, _effective_jwt_secret(settings), algorithm=settings.jwt_algorithm
    )


def decode_refresh_token(settings: Settings, token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            _effective_jwt_secret(settings),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "jti"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    if payload.get("typ") != "refresh":
        raise InvalidTokenError("token type is not refresh")
    return payload


def lookup_refresh_token(session: Session, jti: str) -> models.RefreshToken | None:
    return session.scalars(
        select(models.RefreshToken).where(models.RefreshToken.jti == jti)
    ).first()


def revoke_refresh_token(row: models.RefreshToken) -> None:
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """SQLite drops tzinfo on roundtrip even when the column is DateTime(timezone=True);
    treat naive timestamps as UTC so comparisons don't blow up."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def refresh_token_is_usable(row: models.RefreshToken) -> bool:
    if row.revoked_at is not None:
        return False
    return _as_utc(row.expires_at) > datetime.now(timezone.utc)
