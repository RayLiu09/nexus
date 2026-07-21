"""B6/B7 (§10 阶段 B) — QueryRouterV2 orchestration tests.

Exercises the top-level ``QueryRouterV2.run()`` orchestration across
the three layers (intent → params → dispatcher → composer) with
scripted LLM responses so each fallback + happy path can be verified
without hitting the network or the real registry.

Key surfaces:
* Happy path — intent → params → dispatcher hits a tool → composer
  produces markdown → audit_summary carries all v2 fields.
* Unknown intent short-circuits to §六 pgvector fallback.
* Low-confidence intent also routes to fallback.
* scenario_5 returns the ``scenario_5_template_not_implemented``
  placeholder (P0 stub).
* Dispatcher fallbacks (no_tool_call / param_validation_failed) route
  to fallback, and the ``dispatch_fallback`` field on
  ``audit_summary`` is populated only for LLM-side failures per §8.2.
* pgvector adapter absence still produces a graceful fallback answer.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from nexus_app import models
from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMCallSummary,
    LiteLLMErrorType,
    ToolCall,
    ToolCallingResult,
)
from nexus_app.retrieval.chart_adapter import ChartRegistry
from nexus_app.retrieval.dispatcher_v2 import ToolExecutorRegistry
from nexus_app.retrieval.prompt_profiles_v2 import seed_retrieval_v2_prompts
from nexus_app.retrieval.router_v2 import QueryRouterV2, RouterResult
from nexus_app.retrieval.subject_routing import (
    QuerySubject,
    apply_subject_route_guard,
    resolve_query_subject,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


def _summary() -> LiteLLMCallSummary:
    return LiteLLMCallSummary(
        model_alias="primary-llm",
        request_id="fake",
        latency_ms=1.0,
        status="success",
        input_hash="hash",
    )


class _RoutedLLM:
    """Multi-purpose scripted LLM: dispatches by expected message keyword.

    The dispatcher / composer / intent / param extractor all use the same
    ``llm_client``; we route responses by matching a keyword in the
    prompt content so tests don't have to script an exact call order.
    """

    def __init__(
        self,
        *,
        intent: dict | None = None,
        params: dict | None = None,
        compose_output: str = "# 结果",
        tool_calls: list[ToolCall] | None = None,
        tool_calls_error: LiteLLMCallError | None = None,
    ) -> None:
        self._intent = intent or {"intent": "scenario_1", "confidence": 0.9}
        self._params = params or {"extracted_params": {"query": "q"},
                                    "missing_required": []}
        self._compose_output = compose_output
        self._tool_calls = tool_calls
        self._tool_calls_error = tool_calls_error
        self.calls: list[dict] = []

    def call(self, model_alias, messages, **kwargs):
        content = messages[-1]["content"] if messages else ""
        self.calls.append({"kind": "call", "content": content, "kwargs": kwargs})
        if "意图分类器" in content:
            return json.dumps(self._intent), _summary()
        if "参数抽取器" in content:
            return json.dumps(self._params), _summary()
        if "Markdown 汇总器" in content or "输出规范" in content:
            return self._compose_output, _summary()
        raise AssertionError(f"unexpected call() content: {content[:200]}")

    def call_with_tools(self, model_alias, messages, **kwargs):
        content = messages[-1]["content"] if messages else ""
        self.calls.append({
            "kind": "call_with_tools",
            "content": content,
            "kwargs": kwargs,
        })
        if self._tool_calls_error is not None:
            raise self._tool_calls_error
        return ToolCallingResult(
            content="",
            tool_calls=list(self._tool_calls or []),
            finish_reason="tool_calls",
            summary=_summary(),
        )


class _FakePgvectorAdapter:
    """Returns canned hits — enough for the §六 fallback prompt shape."""

    def __init__(self, hits: list[dict] | None = None,
                 *, raise_exc: Exception | None = None) -> None:
        self._hits = hits or []
        self._raise = raise_exc
        self.calls: list[dict] = []

    def search(self, session, **kwargs):
        self.calls.append(kwargs)
        if self._raise is not None:
            raise self._raise
        return list(self._hits)


@pytest.fixture()
def seeded_session(session):
    seed_retrieval_v2_prompts(session)
    session.commit()
    return session


# ---------------------------------------------------------------------------
# Happy path — dispatcher + composer both succeed
# ---------------------------------------------------------------------------


def test_known_job_subject_overrides_major_only_scenario() -> None:
    from nexus_app.retrieval.intent_v2 import IntentV2Result

    result = apply_subject_route_guard(
        IntentV2Result(intent="scenario_3", confidence=0.94),
        QuerySubject(kind="job", value="无人机飞手"),
    )

    assert result.intent == "scenario_2"
    assert "subject_route_override:job_to_scenario_2" in result.warnings


def test_major_subject_does_not_override_structured_data_intent() -> None:
    from nexus_app.retrieval.intent_v2 import IntentV2Result

    result = apply_subject_route_guard(
        IntentV2Result(intent="scenario_2", confidence=0.94),
        QuerySubject(kind="major", value="无人机应用技术"),
    )

    assert result.intent == "scenario_2"


def test_known_major_basic_information_overrides_scenario_4(session) -> None:
    from nexus_app.retrieval.intent_v2 import IntentV2Result

    session.add(models.MajorProfile(
        id="major-route-profile", normalized_ref_id="major-route-ref",
        asset_version_id="major-route-version", domain_profile="major_profile.v1",
        major_name="网络营销与直播电商", major_code="530704",
        extractor_version="test", evidence={},
    ))
    session.flush()
    query = "网络营销与直播电商专业的基本信息"
    subject = resolve_query_subject(session, query)
    result = apply_subject_route_guard(
        IntentV2Result(intent="scenario_4", confidence=0.88), subject, query,
    )

    assert subject == QuerySubject(kind="major", value="网络营销与直播电商")
    assert result.intent == "scenario_3"
    assert "subject_route_override:major_information_to_scenario_3" in result.warnings


def test_known_major_distribution_question_stays_scenario_2(session) -> None:
    from nexus_app.retrieval.intent_v2 import IntentV2Result

    result = apply_subject_route_guard(
        IntentV2Result(intent="scenario_2", confidence=0.88),
        QuerySubject(kind="major", value="网络营销与直播电商"),
        "网络营销与直播电商专业布点数量",
    )

    assert result.intent == "scenario_2"


class TestHappyPath:
    def test_scenario_1_flows_through_all_three_layers(self, seeded_session):
        tc = ToolCall(
            id="c1",
            name="internal.search_chunks_by_semantic",
            arguments='{"query": "2025 跨境电商政策", "kb": "industry_research_kb"}',
        )
        llm = _RoutedLLM(
            intent={"intent": "scenario_1", "confidence": 0.95},
            params={"extracted_params": {"query": "2025 跨境电商政策"},
                     "missing_required": []},
            compose_output="# 汇总\n\n实际内容",
            tool_calls=[tc],
        )
        exec_reg = ToolExecutorRegistry()
        exec_reg.register(
            "internal.search_chunks_by_semantic",
            lambda *, session, arguments, tool_call_id, chart_registry: {
                "hits": [{"chunk_id": "abc"}],
            },
        )
        router = QueryRouterV2(
            llm_client=llm,
            executor_registry=exec_reg,
            pgvector_adapter=_FakePgvectorAdapter(),
        )
        result = router.run(
            seeded_session,
            query="2025 跨境电商政策",
            route="internal_query",
            caller_type="console_session",
        )
        assert isinstance(result, RouterResult)
        assert result.fallback_reason is None
        assert result.intent == "scenario_1"
        assert result.intent_confidence >= 0.9
        assert result.invoked_tools == ["internal.search_chunks_by_semantic"]
        assert "汇总" in result.markdown
        # v2 audit summary fields present + correctly populated.
        summary = result.audit_summary
        assert summary["route"] == "internal_query"
        assert summary["caller_type"] == "console_session"
        assert summary["intent"] == "scenario_1"
        assert summary["query_route"] == "v2"
        assert summary["invoked_tools"] == ["internal.search_chunks_by_semantic"]
        assert "generated_ratio" in summary


# ---------------------------------------------------------------------------
# §六 unknown fallback
# ---------------------------------------------------------------------------


class TestUnknownFallback:
    def test_unknown_intent_uses_pgvector_and_composes(self, seeded_session):
        llm = _RoutedLLM(
            intent={"intent": "unknown", "confidence": 0.9},
            compose_output="兜底回答",
        )
        pgvector = _FakePgvectorAdapter(hits=[{"chunk_id": "x", "score": 0.5}])
        router = QueryRouterV2(
            llm_client=llm,
            executor_registry=ToolExecutorRegistry(),
            pgvector_adapter=pgvector,
        )
        result = router.run(
            seeded_session, query="无法归类的问题",
            route="open_query", caller_type="api_caller",
        )
        assert result.fallback_reason == "unknown_fallback"
        assert result.intent == "unknown"
        assert "兜底" in result.markdown
        # pgvector was called with the §六 defaults (top_k=20, sim=0.3).
        assert pgvector.calls[0]["top_k"] == 20
        assert pgvector.calls[0]["similarity_threshold"] == 0.3
        assert pgvector.calls[0]["knowledge_type_code"] is None
        # audit summary carries fallback trigger via warnings.
        assert "unknown_intent" in result.warnings

    def test_unknown_fallback_retrieves_outline_scope_after_broad_hit(self, seeded_session):
        root = models.KnowledgeOutlineNode(
            id="fallback-outline-root", normalized_ref_id="fallback-ref", parent_id=None,
            level=0, order_index=0, title="教材", build_run_id="run-1",
            chunk_count=0, fallback_used=False, node_metadata={},
        )
        section = models.KnowledgeOutlineNode(
            id="fallback-outline-section", normalized_ref_id="fallback-ref", parent_id=root.id,
            level=1, order_index=1, title="短视频平台的类型", build_run_id="run-1",
            chunk_count=1, fallback_used=False, node_metadata={},
        )
        chunk = models.KnowledgeChunk(
            id="fallback-outline-chunk", normalized_ref_id="fallback-ref",
            knowledge_type_code="course_textbook", chunk_type="semantic_block",
            chunking_strategy="semantic_repack", source_kind="extracted_from_normalized",
            chunk_index=0, content="社交媒体类短视频平台侧重互动和社交功能。",
            chunk_metadata={}, embedding_status="embedded", source_block_ids=[], locator={},
            knowledge_outline_node_id=section.id,
        )
        seeded_session.add_all([root, section, chunk])
        seeded_session.flush()
        llm = _RoutedLLM(
            intent={"intent": "unknown", "confidence": 0.9},
            compose_output="范围内回答",
        )
        pgvector = _FakePgvectorAdapter(hits=[{
            "nexus_chunk_id": chunk.id,
            "normalized_ref_id": "fallback-ref",
            "score": 0.9,
        }])
        router = QueryRouterV2(
            llm_client=llm,
            executor_registry=ToolExecutorRegistry(),
            pgvector_adapter=pgvector,
        )

        result = router.run(
            seeded_session, query="短视频平台的类型",
            route="internal_query", caller_type="console_session",
        )

        assert result.fallback_reason == "unknown_fallback"
        assert len(pgvector.calls) == 2
        assert pgvector.calls[1]["chunk_ids"] == [chunk.id]
        assert "社交媒体类短视频平台侧重互动和社交功能" in result.markdown
        assert "`fallback-ref` / `fallback-outline-chunk`" in result.markdown

    def test_low_confidence_intent_falls_back(self, seeded_session):
        llm = _RoutedLLM(
            intent={"intent": "scenario_1", "confidence": 0.3},  # below 0.6
            compose_output="兜底",
        )
        pgvector = _FakePgvectorAdapter()
        router = QueryRouterV2(
            llm_client=llm,
            executor_registry=ToolExecutorRegistry(),
            pgvector_adapter=pgvector,
        )
        result = router.run(
            seeded_session, query="q",
            route="internal_query", caller_type="console_session",
        )
        assert result.fallback_reason == "unknown_fallback"
        assert "low_confidence" in result.warnings

    def test_no_tool_call_falls_back_and_records_dispatch_fallback(
        self, seeded_session,
    ):
        llm = _RoutedLLM(
            intent={"intent": "scenario_1", "confidence": 0.9},
            params={"extracted_params": {"query": "q"}, "missing_required": []},
            compose_output="兜底",
            tool_calls=[],  # LLM chose no tool → §1.11 decision #4 fallback
        )
        pgvector = _FakePgvectorAdapter()
        router = QueryRouterV2(
            llm_client=llm,
            executor_registry=ToolExecutorRegistry(),
            pgvector_adapter=pgvector,
        )
        result = router.run(
            seeded_session, query="q",
            route="open_query", caller_type="api_caller",
        )
        assert result.fallback_reason == "unknown_fallback"
        assert result.audit_summary["dispatch_fallback"] == "no_tool_call"

    def test_pgvector_missing_still_produces_answer(self, seeded_session):
        llm = _RoutedLLM(
            intent={"intent": "unknown", "confidence": 0.9},
            compose_output="兜底但无 pgvector",
        )
        router = QueryRouterV2(
            llm_client=llm,
            executor_registry=ToolExecutorRegistry(),
            pgvector_adapter=None,
        )
        result = router.run(
            seeded_session, query="q",
            route="internal_query", caller_type="console_session",
        )
        # Falls back with empty hits — composer still produces text.
        assert result.fallback_reason == "unknown_fallback"
        assert result.markdown  # non-empty


# ---------------------------------------------------------------------------
# scenario_5 placeholder
# ---------------------------------------------------------------------------


class TestScenario5Placeholder:
    def test_scenario_5_returns_placeholder_marker(self, seeded_session):
        llm = _RoutedLLM(
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
        result = router.run(
            seeded_session, query="设计人才培养方案",
            route="internal_query", caller_type="console_session",
        )
        assert result.fallback_reason == "scenario_5_template_not_implemented"
        assert result.audit_summary["template_id"] == "talent_cultivation_plan"
        assert result.intent == "scenario_5"


# ---------------------------------------------------------------------------
# Audit summary invariants
# ---------------------------------------------------------------------------


class TestAuditSummary:
    def test_summary_always_carries_v2_marker(self, seeded_session):
        llm = _RoutedLLM(
            intent={"intent": "unknown", "confidence": 0.9},
            compose_output="ok",
        )
        router = QueryRouterV2(
            llm_client=llm,
            executor_registry=ToolExecutorRegistry(),
            pgvector_adapter=_FakePgvectorAdapter(),
        )
        result = router.run(
            seeded_session, query="q",
            route="open_query", caller_type="api_caller",
        )
        assert result.audit_summary["query_route"] == "v2"
        assert result.audit_summary["route"] == "open_query"
        assert result.audit_summary["caller_type"] == "api_caller"
