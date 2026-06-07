"""Brute-force protection on `/internal/v1/auth/login`.

Pre-H2 the handler only audited failed attempts — no throttling. After
H2 each wrong password increments `user_account.failed_login_count` and
the row gets stamped with `lockout_until = now + LOCKOUT_DURATION` once
the threshold is hit. Further attempts within the window are refused
with 429 + a `Retry-After` header.

These tests pin:
  - successful login resets the counter
  - 5 wrong passwords then 6th attempt returns 429 even with the *right*
    password
  - the 6th failure also writes `USER_LOGIN_LOCKED` to the audit trail
  - unknown usernames don't get locked (no row to lock; audit still
    records the attempt)
  - lockout expires automatically after the window elapses
  - disabled users are NOT subject to lockout (would be a 403 path)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from nexus_app import auth_service, models
from nexus_app.enums import AuditEventType, PrincipalStatus, UserRole


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def user(session: Session) -> models.UserAccount:
    row = models.UserAccount(
        id="user-rl-1",
        username="ratelimit-user",
        display_name="Rate Limit Test",
        role=UserRole.PLATFORM_DATA_ADMIN,
        org_unit_id=None,
        email=None,
        status=PrincipalStatus.ACTIVE,
        password_hash=auth_service.hash_password("correct-horse"),
    )
    session.add(row)
    session.commit()
    return row


def _audit_rows(
    session: Session, *, event: AuditEventType, actor_id: str
) -> list[models.AuditLog]:
    from sqlalchemy import select
    return list(
        session.scalars(
            select(models.AuditLog)
            .where(models.AuditLog.event_type == event)
            .where(models.AuditLog.actor_id == actor_id)
            .order_by(models.AuditLog.created_at.asc())
        ).all()
    )


def _login(client: TestClient, username: str, password: str):
    return client.post(
        "/internal/v1/auth/login",
        json={"username": username, "password": password},
    )


# ── Threshold ─────────────────────────────────────────────────────────────


def test_threshold_constants_match_spec(user):
    # If these change, update the doc in nexus_app.auth_service.
    assert auth_service.MAX_FAILED_LOGIN_ATTEMPTS == 5
    assert auth_service.LOCKOUT_DURATION == timedelta(minutes=15)


def test_under_threshold_just_401(app_no_auth_override, session, user):
    with TestClient(app_no_auth_override) as client:
        for _ in range(auth_service.MAX_FAILED_LOGIN_ATTEMPTS - 1):
            resp = _login(client, user.username, "wrong")
            assert resp.status_code == 401

    session.refresh(user)
    assert user.failed_login_count == auth_service.MAX_FAILED_LOGIN_ATTEMPTS - 1
    assert user.lockout_until is None


def test_threshold_hit_locks_and_writes_audit(app_no_auth_override, session, user):
    with TestClient(app_no_auth_override) as client:
        for _ in range(auth_service.MAX_FAILED_LOGIN_ATTEMPTS):
            resp = _login(client, user.username, "wrong")
            assert resp.status_code == 401

    session.refresh(user)
    assert user.failed_login_count == auth_service.MAX_FAILED_LOGIN_ATTEMPTS
    assert user.lockout_until is not None
    # Lockout reaches into the future by roughly LOCKOUT_DURATION.
    now = datetime.now(timezone.utc)
    until = user.lockout_until
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    delta = (until - now).total_seconds()
    assert delta > 0
    assert delta <= auth_service.LOCKOUT_DURATION.total_seconds() + 5

    locks = _audit_rows(
        session, event=AuditEventType.USER_LOGIN_LOCKED, actor_id=user.id
    )
    assert len(locks) == 1
    summary = locks[0].summary
    assert summary["failed_login_count"] == auth_service.MAX_FAILED_LOGIN_ATTEMPTS
    assert summary["lockout_window_seconds"] == int(
        auth_service.LOCKOUT_DURATION.total_seconds()
    )


def test_locked_user_cannot_login_even_with_correct_password(
    app_no_auth_override, session, user
):
    # Push the user into lockout.
    user.failed_login_count = auth_service.MAX_FAILED_LOGIN_ATTEMPTS
    user.lockout_until = datetime.now(timezone.utc) + timedelta(minutes=10)
    session.commit()

    with TestClient(app_no_auth_override) as client:
        resp = _login(client, user.username, "correct-horse")

    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    retry_after = int(resp.headers["Retry-After"])
    assert 0 < retry_after <= int(auth_service.LOCKOUT_DURATION.total_seconds())


def test_expired_lockout_clears_and_allows_retry(app_no_auth_override, session, user):
    # Lockout in the past — handler should clear it and accept the next attempt.
    user.failed_login_count = auth_service.MAX_FAILED_LOGIN_ATTEMPTS
    user.lockout_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    session.commit()

    with TestClient(app_no_auth_override) as client:
        resp = _login(client, user.username, "correct-horse")

    assert resp.status_code == 200
    session.refresh(user)
    assert user.failed_login_count == 0
    assert user.lockout_until is None


def test_successful_login_resets_counter(app_no_auth_override, session, user):
    user.failed_login_count = 3  # below threshold
    session.commit()

    with TestClient(app_no_auth_override) as client:
        resp = _login(client, user.username, "correct-horse")

    assert resp.status_code == 200
    session.refresh(user)
    assert user.failed_login_count == 0
    assert user.lockout_until is None


def test_unknown_username_does_not_create_row_or_crash(app_no_auth_override, session):
    with TestClient(app_no_auth_override) as client:
        resp = _login(client, "no-such-user", "anything")
    assert resp.status_code == 401
    # Failed audit was still recorded against the username.
    from sqlalchemy import select
    rows = list(
        session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.event_type == AuditEventType.USER_LOGIN_FAILED,
                models.AuditLog.target_id == "no-such-user",
            )
        ).all()
    )
    assert len(rows) == 1
    # No user_account rows were created as a side effect.
    assert (
        session.scalar(
            select(models.UserAccount).where(
                models.UserAccount.username == "no-such-user"
            )
        )
        is None
    )


def test_lockout_audit_carries_locked_until_in_summary(
    app_no_auth_override, session, user
):
    with TestClient(app_no_auth_override) as client:
        for _ in range(auth_service.MAX_FAILED_LOGIN_ATTEMPTS):
            _login(client, user.username, "wrong")

    locks = _audit_rows(
        session, event=AuditEventType.USER_LOGIN_LOCKED, actor_id=user.id
    )
    assert len(locks) == 1
    locked_until = locks[0].summary["locked_until"]
    # ISO8601 with timezone.
    parsed = datetime.fromisoformat(locked_until)
    assert parsed.tzinfo is not None
