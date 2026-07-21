"""B6/B7 (§10 阶段 B) — /internal/v1/query + /open/v1/query endpoints.

Both endpoints are thin FastAPI wrappers over ``QueryRouterV2``. Tests
override the router with a fake so the LLM / database / executors
don't need to be real — the endpoints' own responsibilities are:

* Wire the correct ``route`` + ``caller_type`` labels (internal_query
  + console_session for B7; open_query + api_caller for B6).
* Copy the ``audit_summary`` into the ``SearchQueryExecuted`` event
  and merge in the ``query_hash`` so downstream analytics can join.
* Return the router result as an ``ApiResponse[...]`` envelope.
* Enforce auth via ``require_user`` / ``require_api_caller``
  respectively (verified through the conftest overrides — 401 test
  is handled elsewhere).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_api.query_router_v2_deps import get_query_router_v2
from nexus_app import models
from nexus_app.enums import AuditEventType


class _FakeQueryRouter:
    """Records the arguments it was called with and returns a canned result."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, session, *, query, route, caller_type):
        self.calls.append({
            "query": query, "route": route, "caller_type": caller_type,
        })
        return SimpleNamespace(
            markdown=f"# 回答\n\n{query} 的检索结果",
            raw_markdown="raw",
            audit_summary={
                "route": route,
                "caller_type": caller_type,
                "intent": "scenario_1",
                "intent_confidence": 0.9,
                "invoked_tools": ["internal.search_chunks_by_semantic"],
                "generated_ratio": 0.1,
                "query_route": "v2",
            },
            intent="scenario_1",
            intent_confidence=0.9,
            invoked_tools=["internal.search_chunks_by_semantic"],
            fallback_reason=None,
            warnings=(),
        )


@pytest.fixture()
def fake_router():
    return _FakeQueryRouter()


@pytest.fixture()
def client(app, fake_router, stub_api_caller, session):
    # `/open/v1/query` calls `_assert_caller_still_active` which does a
    # `session.get(models.ApiCaller, caller.id)` — the stub isn't in
    # the DB by default. Persist it so open tests reach the handler.
    session.add(stub_api_caller)
    session.flush()
    app.dependency_overrides[get_query_router_v2] = lambda: fake_router
    return TestClient(app)


# ---------------------------------------------------------------------------
# B7: /internal/v1/query
# ---------------------------------------------------------------------------


class TestInternalQueryEndpoint:
    def test_happy_path_returns_markdown(self, client, fake_router):
        response = client.post(
            "/internal/v1/query", json={"query": "跨境电商 2025 政策"},
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert "跨境电商 2025 政策" in data["markdown"]
        assert data["intent"] == "scenario_1"
        assert data["invoked_tools"] == ["internal.search_chunks_by_semantic"]
        assert data["external_web_results"] == []

    def test_router_receives_internal_route_labels(self, client, fake_router):
        client.post("/internal/v1/query", json={"query": "q"})
        assert fake_router.calls[0]["route"] == "internal_query"
        assert fake_router.calls[0]["caller_type"] == "console_session"

    def test_audit_event_written_with_v2_summary_fields(
        self, client, fake_router, session,
    ):
        client.post("/internal/v1/query", json={"query": "跨境电商"})
        rows = list(session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.event_type
                == AuditEventType.SEARCH_QUERY_EXECUTED,
            )
        ))
        assert rows, "audit log for query_router_v2 must be written"
        summary = rows[-1].summary
        assert summary["route"] == "internal_query"
        assert summary["caller_type"] == "console_session"
        assert summary["query_route"] == "v2"
        assert "query_hash" in summary

    def test_query_field_length_validation(self, client):
        # empty rejected (min_length=1)
        r = client.post("/internal/v1/query", json={"query": ""})
        assert r.status_code == 422
        # oversize rejected (max_length=2048)
        r = client.post(
            "/internal/v1/query", json={"query": "x" * 2049},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# B6: /open/v1/query
# ---------------------------------------------------------------------------


class TestOpenQueryEndpoint:
    def test_happy_path_returns_markdown(self, client, fake_router):
        response = client.post(
            "/open/v1/query", json={"query": "教材类问题"},
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert "教材类问题" in data["markdown"]

    def test_router_receives_open_route_labels(self, client, fake_router):
        client.post("/open/v1/query", json={"query": "q"})
        assert fake_router.calls[0]["route"] == "open_query"
        assert fake_router.calls[0]["caller_type"] == "api_caller"

    def test_audit_event_written_with_api_caller_actor(
        self, client, fake_router, session,
    ):
        client.post("/open/v1/query", json={"query": "q"})
        rows = list(session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.event_type
                == AuditEventType.SEARCH_QUERY_EXECUTED,
                models.AuditLog.actor_type == "api_caller",
            )
        ))
        assert rows
        summary = rows[-1].summary
        assert summary["route"] == "open_query"
        assert summary["caller_type"] == "api_caller"

    def test_query_field_length_validation(self, client):
        r = client.post("/open/v1/query", json={"query": ""})
        assert r.status_code == 422
        r = client.post("/open/v1/query", json={"query": "x" * 2049})
        assert r.status_code == 422
