"""POST /v1/api-callers (mint) and DELETE /v1/api-callers/{id} (revoke).

We focus on:
  - server-minted callers store only the hash and echo plaintext exactly once;
  - revocation flips `revoked_at` and is idempotent;
  - a revoked caller is rejected by `require_api_caller`.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_app import models
from nexus_app.auth_service import hash_api_caller_key


def test_post_api_callers_server_mints_and_only_returns_plaintext_once(app, session):
    client = TestClient(app)
    resp = client.post(
        "/internal/v1/api-callers",
        json={"name": "Upper System Z", "org_scope": [], "permission_scope": []},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]

    plaintext = body["caller_key_plaintext"]
    assert plaintext and plaintext.startswith("nx_")
    # The DB never stored the plaintext.
    assert body["caller_key"] is None

    row = session.scalars(
        select(models.ApiCaller).where(models.ApiCaller.id == body["id"])
    ).one()
    assert row.caller_key is None
    assert row.caller_key_hash == hash_api_caller_key(plaintext)

    # Subsequent GET does NOT surface the plaintext.
    get_resp = client.get(f"/internal/v1/api-callers/{body['id']}")
    assert get_resp.status_code == 200
    # The ApiCallerRead schema has no plaintext field at all.
    assert "caller_key_plaintext" not in get_resp.json()["data"]


def test_post_api_callers_accepts_client_supplied_key(app, session):
    client = TestClient(app)
    resp = client.post(
        "/internal/v1/api-callers",
        json={
            "caller_key": "legacy-key-xyz",
            "name": "Legacy Caller",
        },
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    # Server doesn't re-emit a supplied key; that one is already in caller_key.
    assert body["caller_key_plaintext"] is None
    assert body["caller_key"] == "legacy-key-xyz"

    row = session.scalars(
        select(models.ApiCaller).where(models.ApiCaller.id == body["id"])
    ).one()
    assert row.caller_key == "legacy-key-xyz"
    assert row.caller_key_hash == hash_api_caller_key("legacy-key-xyz")


def test_delete_api_caller_sets_revoked_at_and_is_idempotent(app, session):
    client = TestClient(app)
    minted = client.post(
        "/internal/v1/api-callers",
        json={"name": "Will Be Revoked"},
    ).json()["data"]

    resp = client.delete(f"/internal/v1/api-callers/{minted['id']}")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["revoked_at"] is not None

    # Second call still 200; revoked_at unchanged.
    resp2 = client.delete(f"/internal/v1/api-callers/{minted['id']}")
    assert resp2.status_code == 200
    assert resp2.json()["data"]["revoked_at"] == body["revoked_at"]

    # Audit row written exactly once.
    from nexus_app.enums import AuditEventType

    audits = list(
        session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.event_type == AuditEventType.API_CALLER_REVOKED
            )
        )
    )
    assert len(audits) == 1


def test_revoked_caller_cannot_authenticate(app, session):
    """Drives `require_api_caller` directly so we don't have to stand up a
    RAGFlow adapter just to exercise the auth dependency."""
    from fastapi import HTTPException

    from nexus_api.auth import require_api_caller

    client = TestClient(app)
    minted = client.post("/internal/v1/api-callers", json={"name": "Temp"}).json()["data"]
    plaintext = minted["caller_key_plaintext"]

    # Pre-revocation: dependency returns the caller.
    caller = require_api_caller(
        x_api_key=plaintext, authorization=None, session=session
    )
    assert caller.id == minted["id"]

    # Revoke.
    client.delete(f"/internal/v1/api-callers/{minted['id']}")

    # Post-revocation: dependency raises 403.
    try:
        require_api_caller(x_api_key=plaintext, authorization=None, session=session)
    except HTTPException as exc:
        assert exc.status_code == 403
        assert "revoked" in exc.detail
    else:  # pragma: no cover - the assertion above must fail this branch
        raise AssertionError("expected HTTPException for revoked caller")


def test_delete_api_caller_404_for_unknown_id(app):
    client = TestClient(app)
    resp = client.delete("/internal/v1/api-callers/nope")
    assert resp.status_code == 404
