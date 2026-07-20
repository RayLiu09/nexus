"""QueryRouterV2.run_stream — SSE-oriented streaming orchestration.

Covers:
* Happy path — meta → chunks → final → done (in that exact order).
* Unknown intent short-circuits to a chunk-less meta → final → done.
* scenario_5 stub also skips chunks.
* Dispatcher fallbacks (no_tool_call) route through fallback path.
* Composer LLM error yields an error event AND the final fallback event.
"""
from __future__ import annotations

import json

import pytest

from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMCallSummary,
    LiteLLMErrorType,
    ToolCall,
    ToolCallingResult,
)
from nexus_app.retrieval.dispatcher_v2 import ToolExecutorRegistry
from nexus_app.retrieval.prompt_profiles_v2 import seed_retrieval_v2_prompts
from nexus_app.retrieval.router_v2 import QueryRouterV2, RouterStreamEvent


def _summary() -> LiteLLMCallSummary:
    return LiteLLMCallSummary(
        model_alias="primary-llm", request_id="fake",
        latency_ms=1.0, status="success", input_hash="hash",
    )


class _StreamRoutedLLM:
    """LLM stub that routes both non-stream and stream calls by
    keyword-sniffing the prompt content — same trick as the non-stream
    router tests.
    """

    def __init__(
        self,
        *,
        intent: dict | None = None,
        params: dict | None = None,
        compose_chunks: list[str] | None = None,
        compose_error: LiteLLMCallError | None = None,
        tool_calls: list[ToolCall] | None = None,
    ) -> None:
        self._intent = intent or {"intent": "scenario_1", "confidence": 0.9}
        self._params = params or {"extracted_params": {"query": "q"},
                                    "missing_required": []}
        self._compose_chunks = compose_chunks or ["# 结", "果段落"]
        self._compose_error = compose_error
        self._tool_calls = tool_calls
        self.calls: list[dict] = []

    def call(self, model_alias, messages, **kwargs):
        content = messages[-1]["content"] if messages else ""
        self.calls.append({"kind": "call", "content": content})
        if "意图分类器" in content:
            return json.dumps(self._intent), _summary()
        if "参数抽取器" in content:
            return json.dumps(self._params), _summary()
        # The unknown / scenario_5 fallback paths compose non-streamingly
        # (see `_unknown_fallback_path`) — return a canned string so the
        # router's short-circuit branches can complete.
        if "Markdown 汇总器" in content or "输出规范" in content:
            return "兜底汇总", _summary()
        raise AssertionError(f"unexpected call() content: {content[:120]}")

    def call_with_tools(self, model_alias, messages, **kwargs):
        return ToolCallingResult(
            content="",
            tool_calls=list(self._tool_calls or []),
            finish_reason="tool_calls" if self._tool_calls else "stop",
            summary=_summary(),
        )

    def call_stream(self, model_alias, messages, **kwargs):
        self.calls.append({"kind": "call_stream"})
        if self._compose_error is not None:
            raise self._compose_error
        yield from self._compose_chunks


class _FakePgvector:
    def __init__(self, hits: list[dict] | None = None) -> None:
        self._hits = hits or []

    def search(self, session, **kwargs):
        return list(self._hits)


@pytest.fixture()
def seeded_session(session):
    seed_retrieval_v2_prompts(session)
    session.commit()
    return session


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestStreamHappyPath:
    def test_meta_chunks_final_done_in_order(self, seeded_session):
        tc = ToolCall(
            id="c1",
            name="internal.search_chunks_by_semantic",
            arguments='{"query": "q", "kb": "industry_research_kb"}',
        )
        llm = _StreamRoutedLLM(
            intent={"intent": "scenario_1", "confidence": 0.9},
            params={"extracted_params": {"query": "q"}, "missing_required": []},
            compose_chunks=["# 汇总\n\n", "内容 1", "内容 2"],
            tool_calls=[tc],
        )
        exec_reg = ToolExecutorRegistry()
        exec_reg.register(
            "internal.search_chunks_by_semantic",
            lambda *, session, arguments, tool_call_id, chart_registry: {
                "hits": [{"chunk_id": "a"}],
            },
        )
        router = QueryRouterV2(
            llm_client=llm,
            executor_registry=exec_reg,
            pgvector_adapter=_FakePgvector(),
        )
        events = list(router.run_stream(
            seeded_session, query="q",
            route="internal_query", caller_type="console_session",
        ))
        types = [e.type for e in events]
        # Structural anchors ignoring step events which are additive.
        core_types = [t for t in types if t != "step"]
        assert core_types[0] == "meta"
        assert core_types[-1] == "done"
        assert core_types[-2] == "final"
        assert "chunk" in core_types
        # Meta carries intent + tool list. Meta is the first non-step event.
        meta_event = next(e for e in events if e.type == "meta")
        meta = meta_event.meta or {}
        assert meta["intent"] == "scenario_1"
        assert meta["invoked_tools"] == ["internal.search_chunks_by_semantic"]
        # Concatenated chunk text matches raw_markdown on final result.
        chunk_text = "".join(e.text for e in events if e.type == "chunk")
        final_result = events[-2].result
        assert final_result is not None
        assert final_result.raw_markdown == chunk_text.strip()
        # done carries no payload.
        assert events[-1].result is None


# ---------------------------------------------------------------------------
# Short-circuit paths (no chunks)
# ---------------------------------------------------------------------------


class TestStreamShortCircuits:
    def test_unknown_intent_meta_final_done_only(self, seeded_session):
        llm = _StreamRoutedLLM(
            intent={"intent": "unknown", "confidence": 0.9},
            compose_chunks=["兜底"],
        )
        router = QueryRouterV2(
            llm_client=llm,
            executor_registry=ToolExecutorRegistry(),
            pgvector_adapter=_FakePgvector(),
        )
        events = list(router.run_stream(
            seeded_session, query="q",
            route="internal_query", caller_type="console_session",
        ))
        types = [e.type for e in events]
        # No chunk events on the short-circuit path — the unknown path
        # composes non-streamingly and jumps straight to final.
        assert "chunk" not in types
        core_types = [t for t in types if t != "step"]
        assert core_types == ["meta", "final", "done"]
        meta_event = next(e for e in events if e.type == "meta")
        assert (meta_event.meta or {}).get("fallback_reason") == "unknown_fallback"

    def test_scenario_5_meta_final_done_only(self, seeded_session):
        llm = _StreamRoutedLLM(
            intent={"intent": "scenario_5", "confidence": 0.9},
            params={"extracted_params": {"major_name": "跨境电商"},
                     "missing_required": []},
            tool_calls=[],
        )
        router = QueryRouterV2(
            llm_client=llm,
            executor_registry=ToolExecutorRegistry(),
            pgvector_adapter=None,
        )
        events = list(router.run_stream(
            seeded_session, query="培养方案",
            route="internal_query", caller_type="console_session",
        ))
        core_types = [e.type for e in events if e.type != "step"]
        assert core_types == ["meta", "final", "done"]
        meta_event = next(e for e in events if e.type == "meta")
        assert (meta_event.meta or {})["template_id"] == "talent_cultivation_plan"

    def test_no_tool_call_short_circuits_via_fallback(self, seeded_session):
        llm = _StreamRoutedLLM(
            intent={"intent": "scenario_1", "confidence": 0.9},
            params={"extracted_params": {"query": "q"}, "missing_required": []},
            tool_calls=[],  # dispatcher fallback → unknown path
        )
        router = QueryRouterV2(
            llm_client=llm,
            executor_registry=ToolExecutorRegistry(),
            pgvector_adapter=_FakePgvector(),
        )
        events = list(router.run_stream(
            seeded_session, query="q",
            route="internal_query", caller_type="console_session",
        ))
        core_types = [e.type for e in events if e.type != "step"]
        assert core_types == ["meta", "final", "done"]
        meta_event = next(e for e in events if e.type == "meta")
        assert (meta_event.meta or {}).get("dispatch_fallback") == "no_tool_call"


# ---------------------------------------------------------------------------
# Composer errors mid-stream
# ---------------------------------------------------------------------------


class TestStreamErrors:
    def test_llm_stream_error_yields_error_then_final(self, seeded_session):
        tc = ToolCall(
            id="c1",
            name="internal.search_chunks_by_semantic",
            arguments='{"query": "q", "kb": "industry_research_kb"}',
        )
        llm = _StreamRoutedLLM(
            intent={"intent": "scenario_1", "confidence": 0.9},
            params={"extracted_params": {"query": "q"}, "missing_required": []},
            compose_error=LiteLLMCallError(
                "rate limit", LiteLLMErrorType.RATE_LIMIT,
            ),
            tool_calls=[tc],
        )
        exec_reg = ToolExecutorRegistry()
        exec_reg.register(
            "internal.search_chunks_by_semantic",
            lambda *, session, arguments, tool_call_id, chart_registry: {
                "hits": [],
            },
        )
        router = QueryRouterV2(
            llm_client=llm,
            executor_registry=exec_reg,
            pgvector_adapter=_FakePgvector(),
        )
        events = list(router.run_stream(
            seeded_session, query="q",
            route="internal_query", caller_type="console_session",
        ))
        types = [e.type for e in events]
        assert types.count("meta") == 1
        assert types.count("done") == 1
        assert "error" in types
        assert types.index("error") < types.index("final")
        final_event = next(e for e in events if e.type == "final")
        assert final_event.result is not None
        assert final_event.result.fallback_reason == "llm_call_failed"


# ---------------------------------------------------------------------------
# Step events (Agentic timeline)
# ---------------------------------------------------------------------------


class TestStreamStepEvents:
    def test_happy_path_emits_paired_step_events(self, seeded_session):
        """Every layer emits running + completed step events in
        order, and the output of the completed event carries the
        expected fields for the timeline UI."""
        tc = ToolCall(
            id="c1",
            name="internal.search_chunks_by_semantic",
            arguments='{"query": "q", "kb": "industry_research_kb"}',
        )
        llm = _StreamRoutedLLM(
            intent={"intent": "scenario_1", "confidence": 0.9},
            params={"extracted_params": {"query": "q"}, "missing_required": []},
            compose_chunks=["ok"],
            tool_calls=[tc],
        )
        exec_reg = ToolExecutorRegistry()
        exec_reg.register(
            "internal.search_chunks_by_semantic",
            lambda *, session, arguments, tool_call_id, chart_registry: {"hits": []},
        )
        router = QueryRouterV2(
            llm_client=llm, executor_registry=exec_reg,
            pgvector_adapter=_FakePgvector(),
        )
        events = list(router.run_stream(
            seeded_session, query="q",
            route="internal_query", caller_type="console_session",
        ))
        steps = [e.step for e in events if e.type == "step" and e.step is not None]
        # Every step id must appear twice (running + completed) in the happy path.
        by_id: dict[str, list] = {}
        for s in steps:
            by_id.setdefault(s.id, []).append(s.status)
        assert by_id["intent_classify"] == ["running", "completed"]
        assert by_id["param_extract"] == ["running", "completed"]
        assert by_id["dispatch"] == ["running", "completed"]
        assert by_id["compose"] == ["running", "completed"]
        # Sanity: outputs populated on completed events.
        intent_done = next(s for s in steps
                            if s.id == "intent_classify" and s.status == "completed")
        assert intent_done.output is not None
        assert intent_done.output["intent"] == "scenario_1"
        dispatch_done = next(s for s in steps
                              if s.id == "dispatch" and s.status == "completed")
        assert dispatch_done.output is not None
        assert dispatch_done.output["invoked_tools"] == [
            "internal.search_chunks_by_semantic",
        ]
        # Compose step completes AFTER any chunk event.
        compose_done_idx = next(
            i for i, e in enumerate(events)
            if e.type == "step" and e.step is not None
            and e.step.id == "compose" and e.step.status == "completed"
        )
        last_chunk_idx = max(
            i for i, e in enumerate(events) if e.type == "chunk"
        )
        assert compose_done_idx > last_chunk_idx

    def test_unknown_short_circuit_emits_intent_and_fallback_steps(
        self, seeded_session,
    ):
        llm = _StreamRoutedLLM(
            intent={"intent": "unknown", "confidence": 0.9},
            compose_chunks=["ok"],
        )
        router = QueryRouterV2(
            llm_client=llm, executor_registry=ToolExecutorRegistry(),
            pgvector_adapter=_FakePgvector(),
        )
        events = list(router.run_stream(
            seeded_session, query="q",
            route="internal_query", caller_type="console_session",
        ))
        step_ids = [e.step.id for e in events
                     if e.type == "step" and e.step is not None]
        # Unknown short-circuit: intent + param + fallback only, no
        # dispatch / compose.
        assert set(step_ids) == {"intent_classify", "param_extract", "unknown_fallback"}
        # Every step appears twice.
        for sid in {"intent_classify", "param_extract", "unknown_fallback"}:
            assert step_ids.count(sid) == 2, f"{sid} should be running + completed"

    def test_scenario_5_emits_placeholder_step(self, seeded_session):
        llm = _StreamRoutedLLM(
            intent={"intent": "scenario_5", "confidence": 0.9},
            params={"extracted_params": {"major_name": "跨境电商"},
                     "missing_required": []},
            tool_calls=[],
        )
        router = QueryRouterV2(
            llm_client=llm, executor_registry=ToolExecutorRegistry(),
            pgvector_adapter=None,
        )
        events = list(router.run_stream(
            seeded_session, query="培养方案",
            route="internal_query", caller_type="console_session",
        ))
        step_ids = [e.step.id for e in events
                     if e.type == "step" and e.step is not None]
        # scenario_5: intent + params + dispatch + placeholder.
        assert "scenario_5_placeholder" in step_ids
        # Dispatch also emits (LLM returned zero tool_calls; dispatch
        # completes with the scenario_5_template fallback marker before
        # the placeholder step fires).
        assert "dispatch" in step_ids
