"""Coverage for POST/PATCH/POST-password on /internal/v1/users.

These are the console user-management endpoints exercised by the platform
data admin. Behaviour asserted here:

- create hashes the password with bcrypt and writes a `UserCreated` audit event
- duplicate usernames return 409
- `ops` / `api_caller` roles are rejected at the schema layer
- PATCH updates non-status fields and writes `UserUpdated`
- PATCH that flips status writes `UserStatusChanged`
- password reset re-hashes, clears any lockout, and writes `UserPasswordReset`
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_app import auth_service, models
from nexus_app.enums import AuditEventType, PrincipalStatus, UserRole


@pytest.fixture()
def existing_user(session) -> models.UserAccount:
    user = models.UserAccount(
        username="incumbent@nexus.local",
        display_name="Incumbent Expert",
        role=UserRole.BUSINESS_EXPERT,
        email="incumbent@nexus.local",
        password_hash=auth_service.hash_password("OldPassword!1"),
        status=PrincipalStatus.ACTIVE,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _latest_audit(session, event: AuditEventType) -> models.AuditLog | None:
    return session.scalars(
        select(models.AuditLog)
        .where(models.AuditLog.event_type == event)
        .order_by(models.AuditLog.created_at.desc())
    ).first()


def test_create_user_hashes_password_and_audits(app, session):
    client = TestClient(app)
    resp = client.post(
        "/internal/v1/users",
        json={
            "username": "NewAdmin@Nexus.local",
            "display_name": "New Admin",
            "role": "platform_data_admin",
            "password": "SecretPassw0rd!",
            "description": "Weekend backfill admin",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]
    assert body["username"] == "newadmin@nexus.local"  # normalized lower-case
    assert body["email"] == "newadmin@nexus.local"     # mirrors username
    assert body["description"] == "Weekend backfill admin"
    assert body["role"] == "platform_data_admin"
    assert body["status"] == "active"
    assert "password_hash" not in body  # never leaked

    row = session.get(models.UserAccount, body["id"])
    assert row is not None
    assert row.password_hash is not None and row.password_hash != "SecretPassw0rd!"
    assert auth_service.verify_password("SecretPassw0rd!", row.password_hash)

    audit = _latest_audit(session, AuditEventType.USER_CREATED)
    assert audit is not None
    assert audit.target_id == row.id
    assert audit.summary.get("username") == "newadmin@nexus.local"


def test_create_user_rejects_duplicate_username(app, session, existing_user):
    client = TestClient(app)
    resp = client.post(
        "/internal/v1/users",
        json={
            "username": existing_user.username,
            "display_name": "Collision",
            "role": "business_expert",
            "password": "SecretPassw0rd!",
        },
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.parametrize("bad_role", ["ops", "api_caller"])
def test_create_user_rejects_non_console_roles(app, session, bad_role):
    client = TestClient(app)
    resp = client.post(
        "/internal/v1/users",
        json={
            "username": f"someone-{bad_role}@nexus.local",
            "display_name": "Should Not Persist",
            "role": bad_role,
            "password": "SecretPassw0rd!",
        },
    )
    assert resp.status_code == 422, resp.text


def test_create_user_rejects_non_email_username(app):
    client = TestClient(app)
    resp = client.post(
        "/internal/v1/users",
        json={
            "username": "not-an-email",
            "display_name": "Bad",
            "role": "business_expert",
            "password": "SecretPassw0rd!",
        },
    )
    assert resp.status_code == 422, resp.text


def test_patch_user_updates_display_name_and_description(app, session, existing_user):
    client = TestClient(app)
    resp = client.patch(
        f"/internal/v1/users/{existing_user.id}",
        json={"display_name": "Renamed Expert", "description": "On-call escalations"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["display_name"] == "Renamed Expert"
    assert body["description"] == "On-call escalations"

    audit = _latest_audit(session, AuditEventType.USER_UPDATED)
    assert audit is not None
    assert audit.target_id == existing_user.id
    assert set(audit.summary["changed_fields"]) == {"display_name", "description"}


def test_patch_user_status_disable_emits_status_audit(app, session, existing_user):
    client = TestClient(app)
    resp = client.patch(
        f"/internal/v1/users/{existing_user.id}",
        json={"status": "disabled"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "disabled"

    audit = _latest_audit(session, AuditEventType.USER_STATUS_CHANGED)
    assert audit is not None
    assert audit.summary["status_before"] == "active"
    assert audit.summary["status_after"] == "disabled"


def test_patch_missing_user_returns_404(app):
    client = TestClient(app)
    resp = client.patch(
        "/internal/v1/users/does-not-exist",
        json={"display_name": "Ghost"},
    )
    assert resp.status_code == 404


def test_reset_user_password_clears_lockout(app, session, existing_user):
    from datetime import datetime, timezone

    existing_user.failed_login_count = 5
    existing_user.lockout_until = datetime.now(timezone.utc)
    session.commit()

    client = TestClient(app)
    resp = client.post(
        f"/internal/v1/users/{existing_user.id}/password",
        json={"password": "BrandNewPass!2"},
    )
    assert resp.status_code == 200, resp.text

    session.refresh(existing_user)
    assert existing_user.failed_login_count == 0
    assert existing_user.lockout_until is None
    assert auth_service.verify_password("BrandNewPass!2", existing_user.password_hash)

    audit = _latest_audit(session, AuditEventType.USER_PASSWORD_RESET)
    assert audit is not None
    assert audit.target_id == existing_user.id


def test_change_own_password_verifies_current_and_rotates(app, session, stub_user):
    """Self-service change-password should verify the current password, rehash
    the new one, and emit an audit event with the acting user as actor."""
    # stub_user has password_hash=None from conftest — set a real hash so the
    # current-password check has something to verify against.
    stub_user.password_hash = auth_service.hash_password("OldPass1234")
    session.add(stub_user)
    session.commit()

    client = TestClient(app)
    resp = client.post(
        "/internal/v1/users/me/change-password",
        json={"current_password": "OldPass1234", "new_password": "NewPass1234"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["ok"] is True

    session.refresh(stub_user)
    assert auth_service.verify_password("NewPass1234", stub_user.password_hash)
    assert not auth_service.verify_password("OldPass1234", stub_user.password_hash)

    audit = _latest_audit(session, AuditEventType.USER_PASSWORD_RESET)
    assert audit is not None
    assert audit.target_id == stub_user.id
    assert audit.actor_type == "user"
    assert audit.actor_id == stub_user.id
    assert audit.summary.get("self_service") is True


def test_change_own_password_rejects_wrong_current(app, session, stub_user):
    stub_user.password_hash = auth_service.hash_password("Correct123")
    session.add(stub_user)
    session.commit()

    client = TestClient(app)
    resp = client.post(
        "/internal/v1/users/me/change-password",
        json={"current_password": "Wrong123!", "new_password": "AnotherNew1"},
    )
    assert resp.status_code == 400, resp.text

    session.refresh(stub_user)
    # Password must NOT have been changed.
    assert auth_service.verify_password("Correct123", stub_user.password_hash)
