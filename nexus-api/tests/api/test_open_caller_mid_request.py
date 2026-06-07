"""Caller-revocation mid-request guard on `/open/v1/search` and `/qa`.

`require_api_caller` checks `revoked_at` at request entry, but RAGFlow
round-trips can take seconds. Without a second check before audit
emission, a key revoked while the request is in flight would still get
credited with the access in the audit log and receive a 200 response.
The handlers re-fetch the caller after the adapter call returns and
fail closed with 403 if the row has been revoked.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import auth_service, models
from nexus_app.enums import AuditEventType


@pytest.fixture(autouse=True)
def use_fake_ragflow(monkeypatch):
    """Stub RAGFlow so the test never touches the configured endpoint —
    the adapter return value is irrelevant here: the patched
    `_filter_hits_to_available` raises before it's actually consumed."""
    from nexus_app.index import kb_registry as kr
    from nexus_app.index import ragflow_adapter as ra

    fake = ra.FakeRAGFlowAdapter()
    # Patch the alias *inside* each importer so a freshly-built KbRegistry
    # also sees the fake (kb_registry imported the function at module-load
    # time, not via attribute lookup on `ra`).
    monkeypatch.setattr(ra, "get_ragflow_adapter", lambda settings=None: fake)
    monkeypatch.setattr(kr, "get_ragflow_adapter", lambda settings=None: fake)
    kr._default_registry = None
    yield fake
    kr._default_registry = None


@pytest.fixture()
def caller(session: Session) -> tuple[models.ApiCaller, str]:
    plaintext = auth_service.generate_api_caller_key()
    row = models.ApiCaller(
        id="caller-revoke-mid",
        name="Mid Revoke",
        caller_key=None,
        caller_key_hash=auth_service.hash_api_caller_key(plaintext),
        org_scope=[],
        permission_scope=[],
    )
    session.add(row)
    session.commit()
    return row, plaintext


def _revoke_during(session: Session, caller_id: str) -> callable:
    """Return a side-effect that revokes the caller, suitable for an
    `unittest.mock.patch(...).side_effect`."""

    def _side_effect(*_args, **_kwargs):
        target = session.get(models.ApiCaller, caller_id)
        if target is not None:
            target.revoked_at = datetime.now(timezone.utc)
            session.commit()
        return []

    return _side_effect


def test_search_fails_closed_when_caller_revoked_mid_request(
    app_no_auth_override, session, caller
):
    row, plaintext = caller
    # `_filter_hits_to_available` is called between the adapter call and the
    # audit write. Patch it to revoke the caller at that moment.
    target = "nexus_api.api.open._filter_hits_to_available"
    with patch(target, side_effect=_revoke_during(session, row.id)):
        with TestClient(app_no_auth_override) as client:
            resp = client.get(
                "/open/v1/search?q=hi&top_k=1",
                headers={"X-API-Key": plaintext},
            )
    assert resp.status_code == 403

    # No SEARCH_QUERY_EXECUTED audit row for this caller — fail-closed means
    # no audit either, since the access never officially happened.
    rows = list(
        session.scalars(
            select(models.AuditLog)
            .where(models.AuditLog.event_type == AuditEventType.SEARCH_QUERY_EXECUTED)
            .where(models.AuditLog.actor_id == row.id)
        ).all()
    )
    assert rows == []


def test_qa_fails_closed_when_caller_revoked_mid_request(
    app_no_auth_override, session, caller
):
    row, plaintext = caller
    target = "nexus_api.api.open._filter_hits_to_available"
    with patch(target, side_effect=_revoke_during(session, row.id)):
        with TestClient(app_no_auth_override) as client:
            resp = client.get(
                "/open/v1/qa?q=hi&top_k=1",
                headers={"X-API-Key": plaintext},
            )
    assert resp.status_code == 403

    rows = list(
        session.scalars(
            select(models.AuditLog)
            .where(models.AuditLog.event_type == AuditEventType.QA_ANSWER_GENERATED)
            .where(models.AuditLog.actor_id == row.id)
        ).all()
    )
    assert rows == []
