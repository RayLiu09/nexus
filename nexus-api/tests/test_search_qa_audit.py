"""Tests for search/qa endpoints: permission hook + audit events + source citation."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_app import models
from nexus_app.enums import AuditEventType


@pytest.fixture(autouse=True)
def use_fake_ragflow(monkeypatch):
    """Force FakeRAGFlowAdapter for these tests so we don't hit a real RAGFlow.

    Two patches are needed: kb_registry pulls `get_ragflow_adapter` via
    `from ... import ...`, so the name inside `kb_registry`'s module
    globals is a frozen copy of the original. Patching `ra.get_ragflow_adapter`
    alone does NOT redirect `KbRegistry.__init__`'s lookup."""
    from nexus_app.index import kb_registry as kr
    from nexus_app.index import ragflow_adapter as ra
    fake = ra.FakeRAGFlowAdapter()
    monkeypatch.setattr(ra, "get_ragflow_adapter", lambda settings=None: fake)
    monkeypatch.setattr(kr, "get_ragflow_adapter", lambda settings=None: fake)
    kr._default_registry = None
    yield fake
    kr._default_registry = None


def _seed_caller(session) -> models.ApiCaller:
    caller = models.ApiCaller(
        caller_key="search-test-caller",
        name="Search Test",
        org_scope=["org-1"],
        permission_scope=[],
    )
    session.add(caller)
    session.commit()
    return caller


def _audits(session, event_type: AuditEventType) -> list[models.AuditLog]:
    return list(
        session.scalars(
            select(models.AuditLog).where(models.AuditLog.event_type == event_type)
        )
    )


def _auth_headers(caller_client_id: str) -> dict:
    # Auth middleware verifies by hashed key; for tests we mock by passing client_id
    # via the convention X-Api-Caller-Id (consult require_api_caller for actual scheme).
    return {"X-Api-Caller-Id": caller_client_id}


class TestSearchEndpoint:
    def test_search_returns_results_with_source_citation(self, app, session, monkeypatch):
        from nexus_api.api import internal as v1
        caller = _seed_caller(session)

        async def _override_caller():
            return caller

        from nexus_api.auth import require_api_caller
        app.dependency_overrides[require_api_caller] = lambda: caller

        client = TestClient(app)
        resp = client.get("/open/v1/search?q=test+query&kb=textbook_kb&top_k=2")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "results" in data
        # Fake adapter populates nexus_* fields directly
        for hit in data["results"]:
            assert "normalized_ref_id" in hit
            assert "version_id" in hit
            assert "asset_id" in hit

    def test_search_writes_audit_event(self, app, session):
        caller = _seed_caller(session)
        from nexus_api.auth import require_api_caller
        app.dependency_overrides[require_api_caller] = lambda: caller

        client = TestClient(app)
        client.get("/open/v1/search?q=hello&kb=textbook_kb")
        events = _audits(session, AuditEventType.SEARCH_QUERY_EXECUTED)
        assert events
        last = events[-1]
        assert last.actor_id == caller.id
        assert last.summary["kb"] == "textbook_kb"
        assert "query_hash" in last.summary
        assert isinstance(last.summary.get("hit_normalized_ref_ids"), list)


class TestQAEndpoint:
    def test_qa_returns_sources_with_citation(self, app, session):
        caller = _seed_caller(session)
        from nexus_api.auth import require_api_caller
        app.dependency_overrides[require_api_caller] = lambda: caller

        client = TestClient(app)
        resp = client.get("/open/v1/qa?q=what+is+x&kb=textbook_kb")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "answer" in data
        assert "sources" in data
        for src in data["sources"]:
            assert "normalized_ref_id" in src

    def test_qa_writes_audit_event(self, app, session):
        caller = _seed_caller(session)
        from nexus_api.auth import require_api_caller
        app.dependency_overrides[require_api_caller] = lambda: caller

        client = TestClient(app)
        client.get("/open/v1/qa?q=what+is+nexus&kb=textbook_kb")
        events = _audits(session, AuditEventType.QA_ANSWER_GENERATED)
        assert events
        last = events[-1]
        assert last.actor_id == caller.id
        assert "question_hash" in last.summary
        assert "cited_normalized_ref_ids" in last.summary


class TestPermissionHookNoop:
    def test_filter_passes_hits_through_unchanged(self):
        from nexus_api.permissions import apply_permission_filter
        caller = type("C", (), {"id": "c1", "org_scope": ["org-1"]})()
        hits = [{"chunk_id": "x", "normalized_ref_id": "r1"}, {"chunk_id": "y"}]
        out = apply_permission_filter(caller, hits)
        assert len(out) == 2
        assert out is hits  # identity in P0 noop
