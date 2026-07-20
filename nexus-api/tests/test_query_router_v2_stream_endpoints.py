"""SSE variants of /internal/v1/query and /open/v1/query.

Endpoint tests use a fake QueryRouterV2 that emits a scripted event
sequence — enough to verify frame formatting and audit-write timing
without touching the LLM stack.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_api.query_router_v2_deps import get_query_router_v2
from nexus_app import models
from nexus_app.enums import AuditEventType
from nexus_app.retrieval.router_v2 import RouterResult, RouterStreamEvent


def _fake_result(intent: str = "scenario_1") -> RouterResult:
    return RouterResult(
        markdown="# 汇总\n\n最终 markdown",
        raw_markdown="# 汇总\n\n最终 markdown",
        audit_summary={
            "route": "internal_query",
            "caller_type": "console_session",
            "intent": intent,
            "invoked_tools": ["internal.search_chunks_by_semantic"],
            "query_route": "v2",
        },
        intent=intent,
        intent_confidence=0.95,
        invoked_tools=["internal.search_chunks_by_semantic"],
        fallback_reason=None,
        warnings=(),
    )


class _FakeStreamingRouter:
    """Records inputs and emits a canned event sequence per call."""

    def __init__(self, *, events: list[RouterStreamEvent]) -> None:
        self._events = events
        self.calls: list[dict] = []

    def run(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def run_stream(self, session, *, query, route, caller_type):
        self.calls.append({
            "query": query, "route": route, "caller_type": caller_type,
        })
        yield from self._events


def _happy_events(result: RouterResult) -> list[RouterStreamEvent]:
    return [
        RouterStreamEvent(
            type="meta",
            meta={
                "intent": result.intent,
                "intent_confidence": result.intent_confidence,
                "invoked_tools": result.invoked_tools,
                "chart_ids": [],
            },
        ),
        RouterStreamEvent(type="chunk", text="# 汇总\n\n"),
        RouterStreamEvent(type="chunk", text="最终 markdown"),
        RouterStreamEvent(type="final", result=result),
        RouterStreamEvent(type="done"),
    ]


@pytest.fixture()
def router():
    return _FakeStreamingRouter(events=_happy_events(_fake_result()))


@pytest.fixture()
def client(app, router, stub_api_caller, session):
    session.add(stub_api_caller)
    session.flush()
    app.dependency_overrides[get_query_router_v2] = lambda: router
    return TestClient(app)


def _parse_sse(body: str) -> list[dict[str, str]]:
    """Split an SSE body into a list of `{event, data}` records.

    Handles the standard ``event: X\\ndata: Y\\n\\n`` framing; ignores
    lines outside those two keys so we don't have to model comments /
    heartbeats.
    """
    frames: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw in body.split("\n"):
        line = raw.rstrip()
        if not line:
            if current:
                frames.append(current)
                current = {}
            continue
        if line.startswith("event:"):
            current["event"] = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            current["data"] = line.removeprefix("data:").strip()
    if current:
        frames.append(current)
    return frames


# ---------------------------------------------------------------------------
# B7 — /internal/v1/query/stream
# ---------------------------------------------------------------------------


class TestInternalStreamEndpoint:
    def test_content_type_is_text_event_stream(self, client):
        response = client.post(
            "/internal/v1/query/stream", json={"query": "跨境电商政策"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        # Anti-buffering hint reaches proxies.
        assert response.headers.get("x-accel-buffering") == "no"

    def test_frames_arrive_in_order_with_final_before_done(self, client):
        response = client.post(
            "/internal/v1/query/stream", json={"query": "q"},
        )
        frames = _parse_sse(response.text)
        types = [f.get("event") for f in frames]
        assert types[0] == "meta"
        assert types[-1] == "done"
        assert "final" in types
        assert types.index("final") < types.index("done")

    def test_chunk_events_carry_text_and_concatenate(self, client):
        response = client.post(
            "/internal/v1/query/stream", json={"query": "q"},
        )
        import json as _json
        frames = _parse_sse(response.text)
        chunks = [f for f in frames if f.get("event") == "chunk"]
        assert len(chunks) == 2
        joined = "".join(_json.loads(f["data"])["text"] for f in chunks)
        assert joined == "# 汇总\n\n最终 markdown"

    def test_final_frame_carries_full_result_payload(self, client):
        response = client.post(
            "/internal/v1/query/stream", json={"query": "q"},
        )
        import json as _json
        frames = _parse_sse(response.text)
        final = next(f for f in frames if f.get("event") == "final")
        payload = _json.loads(final["data"])
        assert payload["intent"] == "scenario_1"
        assert payload["audit_summary"]["query_route"] == "v2"

    def test_audit_row_written_after_final(self, client, session, router):
        client.post("/internal/v1/query/stream", json={"query": "q"})
        rows = list(session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.event_type
                == AuditEventType.SEARCH_QUERY_EXECUTED,
                models.AuditLog.target_type == "query_router_v2",
            )
        ))
        assert rows
        summary = rows[-1].summary
        assert summary["route"] == "internal_query"
        assert summary["caller_type"] == "console_session"
        assert "query_hash" in summary

    def test_router_receives_internal_route_labels(self, client, router):
        client.post("/internal/v1/query/stream", json={"query": "q"})
        assert router.calls[0]["route"] == "internal_query"
        assert router.calls[0]["caller_type"] == "console_session"

    def test_query_length_validation(self, client):
        r = client.post("/internal/v1/query/stream", json={"query": ""})
        assert r.status_code == 422
        r = client.post(
            "/internal/v1/query/stream", json={"query": "x" * 2049},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# B6 — /open/v1/query/stream
# ---------------------------------------------------------------------------


class TestOpenStreamEndpoint:
    def test_content_type_is_text_event_stream(self, client):
        response = client.post(
            "/open/v1/query/stream", json={"query": "教材问题"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

    def test_frames_arrive_and_audit_api_caller(self, client, session, router):
        client.post("/open/v1/query/stream", json={"query": "q"})
        assert router.calls[0]["route"] == "open_query"
        assert router.calls[0]["caller_type"] == "api_caller"
        rows = list(session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.event_type
                == AuditEventType.SEARCH_QUERY_EXECUTED,
                models.AuditLog.actor_type == "api_caller",
                models.AuditLog.target_type == "query_router_v2",
            )
        ))
        assert rows


# ---------------------------------------------------------------------------
# Step frames — B4a Agentic timeline event serialisation
# ---------------------------------------------------------------------------


class TestStepFrames:
    def test_step_events_serialize_as_sse_step_frames(
        self, app, stub_api_caller, session,
    ):
        """Verify the SSE serialiser emits `event: step` frames with
        the full step payload shape the frontend timeline consumes."""
        import json as _json
        from nexus_app.retrieval.router_v2 import StepPayload

        class _StepRouter:
            def run_stream(self, session, *, query, route, caller_type):
                yield RouterStreamEvent(
                    type="step",
                    step=StepPayload(
                        id="intent_classify",
                        status="running",
                        label="意图分类",
                        input={"query": query, "threshold": 0.6},
                        started_at_ms=1000,
                    ),
                )
                yield RouterStreamEvent(
                    type="step",
                    step=StepPayload(
                        id="intent_classify",
                        status="completed",
                        label="意图分类",
                        input={"query": query, "threshold": 0.6},
                        output={"intent": "scenario_1", "confidence": 0.9},
                        started_at_ms=1000,
                        completed_at_ms=1050,
                    ),
                )
                yield RouterStreamEvent(
                    type="meta",
                    meta={
                        "intent": "scenario_1",
                        "intent_confidence": 0.9,
                        "invoked_tools": [],
                        "chart_ids": [],
                    },
                )
                yield RouterStreamEvent(type="final", result=_fake_result())
                yield RouterStreamEvent(type="done")

        session.add(stub_api_caller)
        session.flush()
        app.dependency_overrides[get_query_router_v2] = lambda: _StepRouter()
        client = TestClient(app)

        response = client.post(
            "/internal/v1/query/stream", json={"query": "q"},
        )
        assert response.status_code == 200
        frames = []
        current: dict = {}
        for raw in response.text.split("\n"):
            line = raw.rstrip()
            if not line:
                if current:
                    frames.append(current)
                    current = {}
                continue
            if line.startswith("event:"):
                current["event"] = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                current["data"] = line.removeprefix("data:").strip()
        if current:
            frames.append(current)

        step_frames = [f for f in frames if f.get("event") == "step"]
        assert len(step_frames) == 2
        first = _json.loads(step_frames[0]["data"])
        second = _json.loads(step_frames[1]["data"])
        assert first["id"] == "intent_classify"
        assert first["status"] == "running"
        assert first["label"] == "意图分类"
        assert first["input"]["query"] == "q"
        assert first["output"] is None
        assert second["status"] == "completed"
        assert second["output"]["intent"] == "scenario_1"
        assert second["completed_at_ms"] == 1050
