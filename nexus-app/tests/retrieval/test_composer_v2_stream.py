"""Stream variant of B5 composer — MDComposerV2.compose_stream.

Covers:
* Happy path — chunk events yield the LLM deltas in order and the
  final event carries the fully-swapped markdown.
* Chart replacement runs ONCE at stream end (§7.3): mid-stream chunks
  keep placeholders verbatim; final event replaces them.
* Fallbacks (prompt profile missing, LLM error, empty output) emit a
  single ``fallback`` event with the canned ⚠️ payload — no ``chunk``
  events precede.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMCallSummary,
    LiteLLMErrorType,
)
from nexus_app.retrieval.chart_adapter import (
    ChartMeta,
    ChartNode,
    ChartPayload,
    ChartRegistry,
)
from nexus_app.retrieval.composer_v2 import (
    ComposeStreamEvent,
    MDComposerV2,
)
from nexus_app.retrieval.dispatcher_v2 import DispatchResult
from nexus_app.retrieval.prompt_profiles_v2 import seed_retrieval_v2_prompts


def _summary() -> LiteLLMCallSummary:
    return LiteLLMCallSummary(
        model_alias="primary-llm", request_id="fake",
        latency_ms=1.0, status="success", input_hash="hash",
    )


class _StreamLLM:
    def __init__(self, chunks: list[str] | None = None,
                 *, raise_error: LiteLLMCallError | None = None) -> None:
        self._chunks = chunks or []
        self._raise = raise_error
        self.calls: list[dict] = []

    def call(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def call_with_tools(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def call_stream(self, model_alias, messages, **kwargs):
        self.calls.append({"model_alias": model_alias, "kwargs": kwargs})
        if self._raise is not None:
            raise self._raise
        yield from self._chunks


@pytest.fixture()
def seeded_session(session):
    seed_retrieval_v2_prompts(session)
    session.commit()
    return session


def _dispatch(*, chart_registry: ChartRegistry | None = None) -> DispatchResult:
    return DispatchResult(
        intent="scenario_1",
        tool_results=(),
        chart_registry=chart_registry or ChartRegistry(),
    )


class TestStreamHappyPath:
    def test_chunks_yield_in_order_and_final_carries_full_markdown(
        self, seeded_session,
    ):
        llm = _StreamLLM(["# 标", "题\n\n段落 A", " 尾部"])
        composer = MDComposerV2(llm_client=llm)
        events = list(composer.compose_stream(
            seeded_session, query="q", dispatch_result=_dispatch(),
        ))
        chunk_events = [e for e in events if e.type == "chunk"]
        assert [e.text for e in chunk_events] == ["# 标", "题\n\n段落 A", " 尾部"]
        final = [e for e in events if e.type == "final"]
        assert len(final) == 1
        assert final[0].result is not None
        assert final[0].result.raw_markdown == "# 标题\n\n段落 A 尾部"
        assert final[0].result.markdown == "# 标题\n\n段落 A 尾部"

    def test_chart_placeholders_swapped_only_in_final(self, seeded_session):
        registry = ChartRegistry()
        chart_id = registry.register(
            tool_call_id="tc-1",
            payload=ChartPayload(
                nodes=[ChartNode(id="n1", name="Alpha", category="position")],
                edges=[],
                meta=ChartMeta(title="Alpha 图"),
            ),
        )
        # Stream a placeholder split across two chunks — the raw chunks
        # MUST NOT rewrite mid-stream, the final event MUST have the
        # fenced block.
        chunks = [f"# 结果\n\n[[CHART:{chart_id}]]", "\n\n收尾"]
        llm = _StreamLLM(chunks)
        composer = MDComposerV2(llm_client=llm)
        events = list(composer.compose_stream(
            seeded_session, query="q",
            dispatch_result=_dispatch(chart_registry=registry),
        ))
        chunk_text = "".join(e.text for e in events if e.type == "chunk")
        assert f"[[CHART:{chart_id}]]" in chunk_text
        assert "```chart:echarts" not in chunk_text  # §7.3 — no early swap
        final_result = next(e for e in events if e.type == "final").result
        assert final_result is not None
        assert "```chart:echarts" in final_result.markdown
        assert f"[[CHART:{chart_id}]]" not in final_result.markdown


class TestStreamFallbacks:
    def test_missing_prompt_profile_yields_single_fallback_no_chunks(
        self, session,
    ):
        llm = _StreamLLM(["should", "not", "arrive"])
        composer = MDComposerV2(llm_client=llm)
        events = list(composer.compose_stream(
            session, query="q", dispatch_result=_dispatch(),
        ))
        assert not any(e.type == "chunk" for e in events)
        fallback = [e for e in events if e.type == "fallback"]
        assert len(fallback) == 1
        assert fallback[0].result is not None
        assert fallback[0].result.fallback_reason == "prompt_profile_missing"
        # And the fake LLM was never called.
        assert llm.calls == []

    def test_llm_error_mid_stream_falls_back(self, seeded_session):
        llm = _StreamLLM(
            raise_error=LiteLLMCallError(
                "rate limit", LiteLLMErrorType.RATE_LIMIT,
            ),
        )
        composer = MDComposerV2(llm_client=llm)
        events = list(composer.compose_stream(
            seeded_session, query="q", dispatch_result=_dispatch(),
        ))
        fallback = next(e for e in events if e.type == "fallback")
        assert fallback.result is not None
        assert fallback.result.fallback_reason == "llm_call_failed"
        assert "rate_limit" in fallback.result.warnings

    def test_empty_output_yields_fallback(self, seeded_session):
        llm = _StreamLLM(["   ", "\n\n"])
        composer = MDComposerV2(llm_client=llm)
        events = list(composer.compose_stream(
            seeded_session, query="q", dispatch_result=_dispatch(),
        ))
        # chunks still yielded, but stripped result triggers fallback.
        assert any(e.type == "chunk" for e in events)
        fallback = next(e for e in events if e.type == "fallback")
        assert fallback.result is not None
        assert fallback.result.fallback_reason == "empty_llm_output"
