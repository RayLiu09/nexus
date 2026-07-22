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
from nexus_app.retrieval.web_search import ExternalWebResult, WebSearchOutcome
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


class _FakeWebSearch:
    def __init__(self, outcome: WebSearchOutcome | None = None) -> None:
        self.queries: list[str] = []
        self._outcome = outcome

    def search(self, query: str) -> WebSearchOutcome:
        self.queries.append(query)
        if self._outcome is not None:
            return self._outcome
        return WebSearchOutcome(
            results=(ExternalWebResult(
                provider="firecrawl", title="AI agent report",
                url="https://example.org/ai-agent", domain="example.org",
                snippet="Public result", published_at=None,
                retrieved_at="2026-07-21T00:00:00+00:00", rank=1,
            ),),
            provider="firecrawl",
            latency_ms=12.5,
        )


def _compose_call_count(llm: _RoutedLLM) -> int:
    return sum(
        1
        for call in llm.calls
        if call["kind"] == "call"
        and (
            "Markdown 汇总器" in call["content"]
            or "输出规范" in call["content"]
        )
    )


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


def test_industry_trend_unknown_is_corrected_to_scenario_1() -> None:
    from nexus_app.retrieval.intent_v2 import IntentV2Result

    result = apply_subject_route_guard(
        IntentV2Result(intent="unknown", confidence=0.9),
        QuerySubject(kind="unknown"),
        "最新的AI智能体的发展趋势",
    )

    assert result.intent == "scenario_1"
    assert "intent_route_override:industry_information_to_scenario_1" in result.warnings


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
        assert not any(call["kind"] == "call_with_tools" for call in llm.calls)
        assert "deterministic_semantic_dispatch" in result.warnings

    @pytest.mark.parametrize(
        ("intent", "tool_call"),
        [
            ("scenario_1", ToolCall(
                id="web-s1", name="internal.search_chunks_by_semantic",
                arguments='{"query":"最新AI智能体的发展趋势","kb":"industry_research_kb"}',
            )),
            ("scenario_4", ToolCall(
                id="web-s4", name="internal.search_chunks_by_semantic",
                arguments='{"query":"AI智能体是什么","kb":"course_textbook"}',
            )),
        ],
    )
    def test_eligible_empty_local_result_uses_web_search(
        self, seeded_session, intent, tool_call,
    ):
        llm = _RoutedLLM(
            intent={"intent": intent, "confidence": 0.95},
            params={"extracted_params": {"query": "q"}, "missing_required": []},
            compose_output="# 本地无命中",
            tool_calls=[tool_call],
        )
        registry = ToolExecutorRegistry()
        registry.register(
            "internal.search_chunks_by_semantic",
            lambda **kwargs: {"hits": []},
        )
        web = _FakeWebSearch()
        result = QueryRouterV2(
            llm_client=llm, executor_registry=registry,
            pgvector_adapter=_FakePgvectorAdapter(), web_search_client=web,
        ).run(seeded_session, query="最新AI智能体的发展趋势", route="internal_query", caller_type="console_session")

        assert web.queries == ["最新AI智能体的发展趋势"]
        assert result.external_web_results[0]["url"] == "https://example.org/ai-agent"
        assert result.audit_summary["online_search_requested"] is True
        assert result.audit_summary["external_result_domains"] == ["example.org"]
        assert "Public result" not in repr(result.audit_summary)
        assert "本地无命中" not in result.markdown
        assert "公开网络实时结果" in result.markdown
        assert result.audit_summary["generated_ratio"] == 0.0
        assert _compose_call_count(llm) == 0

    @pytest.mark.parametrize("intent", ["scenario_1", "scenario_4"])
    def test_eligible_empty_local_result_without_web_results_skips_composer(
        self, seeded_session, intent,
    ):
        tool_call = ToolCall(
            id="empty-web", name="internal.search_chunks_by_semantic",
            arguments='{"query":"AI智能体的发展趋势","kb":"industry_research_kb"}',
        )
        llm = _RoutedLLM(
            intent={"intent": intent, "confidence": 0.95},
            params={"extracted_params": {"query": "q"}, "missing_required": []},
            compose_output="# 不应出现",
            tool_calls=[tool_call],
        )
        registry = ToolExecutorRegistry()
        registry.register(
            "internal.search_chunks_by_semantic",
            lambda **kwargs: {"hits": [], "count": "0"},
        )
        web = _FakeWebSearch(WebSearchOutcome(
            provider="firecrawl",
            warning="external_search_unavailable",
            error_type="timeout",
        ))

        result = QueryRouterV2(
            llm_client=llm,
            executor_registry=registry,
            pgvector_adapter=_FakePgvectorAdapter(),
            web_search_client=web,
        ).run(
            seeded_session,
            query="AI智能体的发展趋势",
            route="internal_query",
            caller_type="console_session",
        )

        assert web.queries == ["AI智能体的发展趋势"]
        assert result.external_web_results == ()
        assert result.audit_summary["generated_ratio"] == 0.0
        assert result.audit_summary["external_search_error_type"] == "timeout"
        assert "公开网络检索当前不可用或未返回结果" in result.markdown
        assert "不应出现" not in result.markdown
        assert _compose_call_count(llm) == 0

    @pytest.mark.parametrize(
        ("intent", "tool_call", "payload", "expected"),
        [
            (
                "scenario_2",
                ToolCall(
                    id="job-empty",
                    name="internal.get_job_demand_role_graph",
                    arguments='{"job_title":"不存在岗位"}',
                ),
                {"found": False, "records": [], "count": 0},
                "未检索到匹配的岗位需求、职业能力或专业布点结构化数据",
            ),
            (
                "scenario_3",
                ToolCall(
                    id="major-empty",
                    name="internal.query_major_information",
                    arguments=(
                        '{"major_name":"不存在专业",'
                        '"units":["basic_identity"]}'
                    ),
                ),
                {"found": False, "units": {"basic_identity": {"status": "missing"}}},
                "未检索到可核验的专业信息或专业图谱数据",
            ),
        ],
    )
    def test_scenario_2_and_3_empty_assets_skip_composer(
        self, seeded_session, intent, tool_call, payload, expected,
    ):
        llm = _RoutedLLM(
            intent={"intent": intent, "confidence": 0.95},
            params={"extracted_params": {}, "missing_required": []},
            compose_output="# 不应出现",
            tool_calls=[tool_call],
        )
        registry = ToolExecutorRegistry()
        registry.register(tool_call.name, lambda **kwargs: payload)

        result = QueryRouterV2(
            llm_client=llm,
            executor_registry=registry,
            pgvector_adapter=_FakePgvectorAdapter(),
            web_search_client=_FakeWebSearch(),
        ).run(
            seeded_session,
            query="不存在的数据资产",
            route="internal_query",
            caller_type="console_session",
        )

        assert expected in result.markdown
        assert "不应出现" not in result.markdown
        assert result.external_web_results == ()
        assert result.audit_summary["online_search_requested"] is False
        assert result.audit_summary["generated_ratio"] == 0.0
        assert _compose_call_count(llm) == 0

    @pytest.mark.parametrize("intent", ["scenario_2", "scenario_3"])
    def test_structured_and_major_scenarios_never_use_web_search(self, intent):
        web = _FakeWebSearch()
        router = QueryRouterV2(
            llm_client=_RoutedLLM(), executor_registry=ToolExecutorRegistry(),
            web_search_client=web,
        )
        from nexus_app.retrieval.dispatcher_v2 import DispatchResult, ToolResult

        outcome = router._maybe_web_search(
            query="平面设计师岗位信息",
            intent=intent,
            dispatch_result=DispatchResult(intent=intent, tool_results=(ToolResult(
                tool_call_id="empty", name="internal.query_job_demand", arguments={},
                ok=True, result={"records": []},
            ),)),
        )

        assert outcome is None
        assert web.queries == []

    def test_scenario_4_uses_deterministic_semantic_only(self, seeded_session):
        llm = _RoutedLLM(
            intent={"intent": "scenario_4", "confidence": 0.95},
            params={"extracted_params": {"query": "短视频平台的类型"},
                    "missing_required": []},
            compose_output="# 教材汇总",
            tool_calls=[],
        )
        registry = ToolExecutorRegistry()
        calls: list[dict] = []

        def _semantic(**kwargs):
            calls.append(kwargs["arguments"])
            return {"hits": [{"chunk_id": "textbook-chunk"}]}

        registry.register("internal.search_chunks_by_semantic", _semantic)
        registry.register(
            "internal.get_outline_subtree",
            lambda **kwargs: pytest.fail("outline subtree must not be invoked"),
        )
        registry.register(
            "internal.get_evidence_graph_by_ref",
            lambda **kwargs: pytest.fail("evidence graph must not be invoked"),
        )

        result = QueryRouterV2(
            llm_client=llm,
            executor_registry=registry,
            pgvector_adapter=_FakePgvectorAdapter(),
            web_search_client=_FakeWebSearch(),
        ).run(
            seeded_session,
            query="短视频平台的类型",
            route="internal_query",
            caller_type="console_session",
        )

        assert result.invoked_tools == ["internal.search_chunks_by_semantic"]
        assert calls == [{"query": "短视频平台的类型", "top_k": 10, "expand_queries": True}]
        assert not any(call["kind"] == "call_with_tools" for call in llm.calls)
        assert result.audit_summary["online_search_requested"] is False

    def test_scenario_4_practical_training_and_outline_node_args(self, seeded_session):
        llm = _RoutedLLM(
            intent={"intent": "scenario_4", "confidence": 0.95},
            params={"extracted_params": {
                "query": "短视频实训任务操作步骤",
                "outline_node": "outline-1",
            }, "missing_required": []},
            compose_output="# 实训汇总",
            tool_calls=[],
        )
        registry = ToolExecutorRegistry()
        calls: list[dict] = []
        registry.register(
            "internal.search_chunks_by_semantic",
            lambda **kwargs: calls.append(kwargs["arguments"]) or {
                "hits": [{"chunk_id": "training-chunk"}],
            },
        )

        result = QueryRouterV2(
            llm_client=llm,
            executor_registry=registry,
            pgvector_adapter=_FakePgvectorAdapter(),
        ).run(
            seeded_session,
            query="短视频实训任务操作步骤",
            route="internal_query",
            caller_type="console_session",
        )

        assert result.invoked_tools == ["internal.search_chunks_by_semantic"]
        assert calls[0]["kb"] == "practical_training_kb"
        assert calls[0]["outline_node"] == "outline-1"
        assert not any(call["kind"] == "call_with_tools" for call in llm.calls)

    @pytest.mark.parametrize(
        ("intent", "tool_call"),
        [
            ("scenario_2", ToolCall(
                id="s2", name="internal.query_job_demand",
                arguments='{ "major": "电子商务" }',
            )),
            ("scenario_3", ToolCall(
                id="s3", name="internal.query_major_information",
                arguments='{ "major_name": "电子商务", "units": ["basic_identity"] }',
            )),
        ],
    )
    def test_scenario_2_and_3_still_use_llm_dispatcher(
        self, seeded_session, intent, tool_call,
    ):
        llm = _RoutedLLM(
            intent={"intent": intent, "confidence": 0.95},
            params={"extracted_params": {}, "missing_required": []},
            compose_output="# 结构化汇总",
            tool_calls=[tool_call],
        )
        registry = ToolExecutorRegistry()
        registry.register(tool_call.name, lambda **kwargs: {"records": [{"id": "r1"}]})

        result = QueryRouterV2(
            llm_client=llm,
            executor_registry=registry,
            pgvector_adapter=_FakePgvectorAdapter(),
            web_search_client=_FakeWebSearch(),
        ).run(
            seeded_session,
            query="电子商务专业信息",
            route="internal_query",
            caller_type="console_session",
        )

        assert result.intent == intent
        assert any(call["kind"] == "call_with_tools" for call in llm.calls)
        assert result.audit_summary["online_search_requested"] is False


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
        web = _FakeWebSearch()
        router = QueryRouterV2(
            llm_client=llm,
            executor_registry=ToolExecutorRegistry(),
            pgvector_adapter=pgvector,
            web_search_client=web,
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
        assert web.queries == []

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
        registry = ToolExecutorRegistry()
        registry.register(
            "internal.search_chunks_by_semantic",
            lambda **kwargs: {"hits": [], "answer_contexts": []},
        )
        web = _FakeWebSearch()
        router = QueryRouterV2(
            llm_client=llm,
            executor_registry=registry,
            pgvector_adapter=_FakePgvectorAdapter(),
            web_search_client=web,
        )
        result = router.run(
            seeded_session, query="q",
            route="open_query", caller_type="api_caller",
        )
        assert result.fallback_reason is None
        assert result.audit_summary["dispatch_fallback"] is None
        assert result.intent == "scenario_1"
        assert not any(call["kind"] == "call_with_tools" for call in llm.calls)
        assert web.queries == ["q"]
        assert result.external_web_results[0]["provider"] == "firecrawl"
        assert "公开网络实时结果" in result.markdown
        assert _compose_call_count(llm) == 0

    def test_scenario_1_embedding_failure_does_not_use_web_search(
        self, seeded_session,
    ):
        llm = _RoutedLLM(
            intent={"intent": "scenario_1", "confidence": 0.9},
            params={"extracted_params": {"query": "2025年直播电商的发展趋势"},
                    "missing_required": []},
            compose_output="不应出现",
            tool_calls=[],
        )
        registry = ToolExecutorRegistry()

        def _raise_embedding(**kwargs):
            raise RuntimeError(
                "EmbeddingClientError: LiteLLM embedding request failed",
            )

        registry.register("internal.search_chunks_by_semantic", _raise_embedding)
        web = _FakeWebSearch()

        result = QueryRouterV2(
            llm_client=llm,
            executor_registry=registry,
            pgvector_adapter=_FakePgvectorAdapter(),
            web_search_client=web,
        ).run(
            seeded_session,
            query="2025年直播电商的发展趋势",
            route="open_query",
            caller_type="api_caller",
        )

        assert result.intent == "scenario_1"
        assert result.fallback_reason == "local_retrieval_unavailable"
        assert result.audit_summary["online_search_requested"] is False
        assert result.audit_summary["generated_ratio"] == 0.0
        assert web.queries == []
        assert result.external_web_results == ()
        assert "本地语义检索链路当前不可用" in result.markdown
        assert _compose_call_count(llm) == 0

    def test_scenario_1_dispatch_fallback_tries_semantic_chunks_before_web(
        self, seeded_session,
    ):
        llm = _RoutedLLM(
            intent={"intent": "scenario_1", "confidence": 0.9},
            params={"extracted_params": {"query": "直播电商行业发展面临的挑战和成因"},
                    "missing_required": []},
            compose_output="# 平台资料汇总\n\n直播电商挑战来自平台治理。",
            tool_calls=[],
        )
        registry = ToolExecutorRegistry()
        registry.register(
            "internal.search_chunks_by_semantic",
            lambda **kwargs: {
                "hits": [{
                    "nexus_chunk_id": "industry-chunk-1",
                    "normalized_ref_id": "industry-ref",
                    "score": 0.86,
                }],
                "answer_contexts": [],
            },
        )
        web = _FakeWebSearch()

        result = QueryRouterV2(
            llm_client=llm,
            executor_registry=registry,
            pgvector_adapter=_FakePgvectorAdapter(),
            web_search_client=web,
        ).run(
            seeded_session,
            query="直播电商行业发展面临的挑战和成因",
            route="open_query",
            caller_type="api_caller",
        )

        assert result.intent == "scenario_1"
        assert result.invoked_tools == ["internal.search_chunks_by_semantic"]
        assert result.audit_summary["dispatch_fallback"] is None
        assert result.audit_summary["online_search_requested"] is False
        assert not any(call["kind"] == "call_with_tools" for call in llm.calls)
        assert web.queries == []
        assert "平台资料汇总" in result.markdown
        assert _compose_call_count(llm) == 1

    def test_scenario_1_dispatch_fallback_uses_web_only_after_semantic_empty(
        self, seeded_session,
    ):
        llm = _RoutedLLM(
            intent={"intent": "scenario_1", "confidence": 0.9},
            params={"extracted_params": {"query": "最新AI智能体的发展趋势"},
                    "missing_required": []},
            compose_output="不应出现",
            tool_calls=[],
        )
        registry = ToolExecutorRegistry()
        registry.register(
            "internal.search_chunks_by_semantic",
            lambda **kwargs: {"hits": [], "answer_contexts": []},
        )
        web = _FakeWebSearch()

        result = QueryRouterV2(
            llm_client=llm,
            executor_registry=registry,
            pgvector_adapter=_FakePgvectorAdapter(),
            web_search_client=web,
        ).run(
            seeded_session,
            query="最新AI智能体的发展趋势",
            route="open_query",
            caller_type="api_caller",
        )

        assert result.intent == "scenario_1"
        assert result.invoked_tools == ["internal.search_chunks_by_semantic"]
        assert result.audit_summary["dispatch_fallback"] is None
        assert result.audit_summary["generated_ratio"] == 0.0
        assert not any(call["kind"] == "call_with_tools" for call in llm.calls)
        assert web.queries == ["最新AI智能体的发展趋势"]
        assert "公开网络实时结果" in result.markdown
        assert _compose_call_count(llm) == 0

    def test_industry_trend_dispatch_fallback_uses_web_search_without_composer(
        self, seeded_session,
    ):
        llm = _RoutedLLM(
            intent={"intent": "unknown", "confidence": 0.9},
            params={"extracted_params": {"query": "q"}, "missing_required": []},
            compose_output="不应出现",
            tool_calls=[],
        )
        registry = ToolExecutorRegistry()
        registry.register(
            "internal.search_chunks_by_semantic",
            lambda **kwargs: {"hits": [], "answer_contexts": []},
        )
        web = _FakeWebSearch()
        router = QueryRouterV2(
            llm_client=llm,
            executor_registry=registry,
            pgvector_adapter=_FakePgvectorAdapter(),
            web_search_client=web,
        )

        result = router.run(
            seeded_session,
            query="最新AI智能体的发展趋势",
            route="open_query",
            caller_type="api_caller",
        )

        assert result.fallback_reason is None
        assert result.intent == "scenario_1"
        assert web.queries == ["最新AI智能体的发展趋势"]
        assert result.external_web_results[0]["source_type"] == "external_web"
        assert result.audit_summary["generated_ratio"] == 0.0
        assert not any(call["kind"] == "call_with_tools" for call in llm.calls)
        assert "公开网络实时结果" in result.markdown
        assert _compose_call_count(llm) == 0

    def test_stream_industry_trend_unknown_override_reaches_web_search(
        self, seeded_session,
    ):
        llm = _RoutedLLM(
            intent={"intent": "unknown", "confidence": 0.9},
            params={"extracted_params": {"query": "q"}, "missing_required": []},
            compose_output="不应出现",
            tool_calls=[],
        )
        registry = ToolExecutorRegistry()
        registry.register(
            "internal.search_chunks_by_semantic",
            lambda **kwargs: {"hits": [], "answer_contexts": []},
        )
        web = _FakeWebSearch()
        router = QueryRouterV2(
            llm_client=llm,
            executor_registry=registry,
            pgvector_adapter=_FakePgvectorAdapter(),
            web_search_client=web,
        )

        events = list(router.run_stream(
            seeded_session,
            query="最新AI智能体的发展趋势",
            route="open_query",
            caller_type="api_caller",
        ))
        final = [event.result for event in events if event.type == "final"][0]

        assert final is not None
        assert final.intent == "scenario_1"
        assert web.queries == ["最新AI智能体的发展趋势"]
        assert final.audit_summary["generated_ratio"] == 0.0
        assert "公开网络实时结果" in final.markdown
        assert _compose_call_count(llm) == 0

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
