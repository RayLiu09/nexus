"""Coverage for /v1/auth/{login,refresh,logout}.

Tests load a UserAccount with a bcrypt password hash, then drive the FastAPI
TestClient through the same flow nexus-console exercises via its route
handlers. We assert on:
  - happy-path login returns access+refresh tokens and a user payload that
    matches the JwtPayload contract the console decodes;
  - refresh rotates the jti and invalidates the old token;
  - logout revokes the supplied refresh jti idempotently;
  - audit log rows are written for each terminal outcome.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_app import auth_service, models
from nexus_app.config import get_settings
from nexus_app.enums import AuditEventType, PrincipalStatus, UserRole


@pytest.fixture()
def seeded_user(session) -> models.UserAccount:
    org = models.OrgUnit(code="D1", name="Domain One")
    session.add(org)
    session.flush()
    user = models.UserAccount(
        username="alice",
        display_name="Alice Admin",
        role=UserRole.PLATFORM_DATA_ADMIN,
        org_unit_id=org.id,
        password_hash=auth_service.hash_password("correcthorse"),
        status=PrincipalStatus.ACTIVE,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def test_login_returns_tokens_and_user_payload(app, session, seeded_user):
    client = TestClient(app)
    resp = client.post(
        "/internal/v1/auth/login",
        json={"username": "alice", "password": "correcthorse"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]

    user = body["user"]
    assert user["id"] == seeded_user.id
    assert user["username"] == "alice"
    assert user["display_name"] == "Alice Admin"
    assert user["role"] == UserRole.PLATFORM_DATA_ADMIN.value
    assert user["org_name"] == "Domain One"

    # Access token decodes and carries the sub claim console relies on.
    settings = get_settings()
    payload = auth_service.decode_access_token(settings, body["access_token"])
    assert payload["sub"] == seeded_user.id
    assert payload["typ"] == "access"

    # An audit row was written.
    audits = list(
        session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.event_type == AuditEventType.USER_LOGIN_SUCCEEDED
            )
        )
    )
    assert len(audits) == 1
    assert audits[0].target_id == seeded_user.id


def test_login_rejects_wrong_password(app, session, seeded_user):
    client = TestClient(app)
    resp = client.post(
        "/internal/v1/auth/login",
        json={"username": "alice", "password": "wrong"},
    )
    assert resp.status_code == 401
    audits = list(
        session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.event_type == AuditEventType.USER_LOGIN_FAILED
            )
        )
    )
    assert len(audits) == 1


def test_login_rejects_unknown_user(app, session):
    client = TestClient(app)
    resp = client.post(
        "/internal/v1/auth/login",
        json={"username": "ghost", "password": "x"},
    )
    assert resp.status_code == 401


def test_login_rejects_disabled_user(app, session, seeded_user):
    seeded_user.status = PrincipalStatus.DISABLED
    session.commit()
    client = TestClient(app)
    resp = client.post(
        "/internal/v1/auth/login",
        json={"username": "alice", "password": "correcthorse"},
    )
    assert resp.status_code == 403


def test_refresh_rotates_jti_and_invalidates_old_token(app, session, seeded_user):
    client = TestClient(app)
    login = client.post(
        "/internal/v1/auth/login",
        json={"username": "alice", "password": "correcthorse"},
    ).json()["data"]
    old_refresh = login["refresh_token"]

    resp = client.post("/internal/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert resp.status_code == 200, resp.text
    new = resp.json()["data"]
    assert new["access_token"]
    assert new["refresh_token"] != old_refresh

    # Reusing the old refresh inside the short rotation grace window is
    # idempotent, covering concurrent browser refresh requests.
    replay = client.post("/internal/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert replay.status_code == 200, replay.text
    replayed = replay.json()["data"]
    assert replayed["refresh_token"] == new["refresh_token"]

    # Two refresh-token rows exist (rotated chain), and the first is revoked
    # with a pointer to the child jti.
    rows = list(session.scalars(select(models.RefreshToken)))
    assert len(rows) == 2
    revoked = [r for r in rows if r.revoked_at is not None]
    assert len(revoked) == 1
    active = [r for r in rows if r.revoked_at is None]
    assert revoked[0].rotated_to_jti == active[0].jti


def test_refresh_rejects_garbage_token(app, session):
    client = TestClient(app)
    resp = client.post("/internal/v1/auth/refresh", json={"refresh_token": "not-a-jwt"})
    assert resp.status_code == 401


def test_refresh_rejects_expired_token(app, session, seeded_user):
    settings = get_settings()
    # Mint a refresh row but stamp it in the past.
    jti, row = auth_service.issue_refresh_token(
        session, settings, user_id=seeded_user.id
    )
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    session.commit()
    # Encode a JWT whose `exp` matches the row's expired_at (so the decode step
    # won't pre-empt the DB check) — manually build one with a past exp.
    past_payload = {
        "sub": seeded_user.id,
        "jti": jti,
        "iat": int((datetime.now(timezone.utc) - timedelta(seconds=60)).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(seconds=300)).timestamp()),
        "iss": settings.jwt_issuer,
        "typ": "refresh",
    }
    token = jwt.encode(
        past_payload,
        auth_service._effective_jwt_secret(settings),
        algorithm=settings.jwt_algorithm,
    )

    client = TestClient(app)
    resp = client.post("/internal/v1/auth/refresh", json={"refresh_token": token})
    assert resp.status_code == 401


def test_logout_revokes_refresh_and_is_idempotent(app, session, seeded_user):
    client = TestClient(app)
    refresh = client.post(
        "/internal/v1/auth/login",
        json={"username": "alice", "password": "correcthorse"},
    ).json()["data"]["refresh_token"]

    resp = client.post("/internal/v1/auth/logout", json={"refresh_token": refresh})
    assert resp.status_code == 200
    assert resp.json()["data"]["ok"] is True

    # Second logout still returns 200.
    resp2 = client.post("/internal/v1/auth/logout", json={"refresh_token": refresh})
    assert resp2.status_code == 200

    # The refresh row is revoked exactly once.
    rows = list(session.scalars(select(models.RefreshToken)))
    assert len(rows) == 1
    assert rows[0].revoked_at is not None

    # And refresh is now rejected.
    bounce = client.post("/internal/v1/auth/refresh", json={"refresh_token": refresh})
    assert bounce.status_code == 401


def test_logout_tolerates_invalid_token(app, session):
    client = TestClient(app)
    resp = client.post("/internal/v1/auth/logout", json={"refresh_token": "not-a-jwt"})
    assert resp.status_code == 200
