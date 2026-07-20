"""B5 (§10 阶段 B) — MDComposerV2 tests.

Covers:
* Prompt build carries all four placeholders + user-visible content.
* Happy path — LLM output flows through unchanged when no charts.
* Chart placeholder replacement — registered ids become fenced blocks;
  hallucinated ids stay verbatim and surface in ``hallucination_ids``;
  registered-but-unreferenced ids surface in ``unused_ids``.
* generated_ratio — counts `> ⚠️` blockquote wrappers correctly.
* Fallbacks — missing prompt profile, LLM error, empty LLM output.
* Failed tool results are surfaced in the prompt (so the LLM knows
  a tool ran and returned nothing) rather than silently dropped.
"""
from __future__ import annotations

import json
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
    make_chart_id,
)
from nexus_app.retrieval.composer_v2 import (
    MDComposerV2,
    _compute_generated_ratio,
    _serialise_tool_results,
)
from nexus_app.retrieval.dispatcher_v2 import (
    DispatchResult,
    ToolResult,
)
from nexus_app.retrieval.prompt_profiles_v2 import seed_retrieval_v2_prompts


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


class _ScriptedLLM:
    def __init__(self, response: str = "", *, raise_error=None) -> None:
        self._response = response
        self._raise_error = raise_error
        self.calls: list[dict] = []

    def call(self, model_alias, messages, **kwargs):
        self.calls.append({
            "model_alias": model_alias,
            "messages": messages,
            "kwargs": kwargs,
        })
        if self._raise_error is not None:
            raise self._raise_error
        return self._response, _summary()

    def call_with_tools(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError


@pytest.fixture()
def seeded_session(session):
    seed_retrieval_v2_prompts(session)
    session.commit()
    return session


def _dispatch(
    *,
    intent: str = "scenario_1",
    tool_results: tuple[ToolResult, ...] = (),
    chart_registry: ChartRegistry | None = None,
) -> DispatchResult:
    return DispatchResult(
        intent=intent,
        tool_results=tool_results,
        chart_registry=chart_registry or ChartRegistry(),
    )


def _sample_chart() -> ChartPayload:
    return ChartPayload(
        nodes=[ChartNode(id="n1", name="新媒体运营", category="position")],
        edges=[],
        meta=ChartMeta(title="示例图", source_ref="ref-1"),
    )


# ---------------------------------------------------------------------------
# Prompt build
# ---------------------------------------------------------------------------


class TestPromptBuild:
    def test_prompt_carries_all_placeholders_replaced(self, seeded_session):
        llm = _ScriptedLLM("# 回答\n实际结果内容")
        composer = MDComposerV2(llm_client=llm)
        composer.compose(
            seeded_session,
            query="2025 跨境电商政策",
            dispatch_result=_dispatch(
                intent="scenario_1",
                tool_results=(ToolResult(
                    tool_call_id="c1",
                    name="internal.search_chunks_by_semantic",
                    arguments={"query": "跨境电商政策", "kb": "industry_research_kb"},
                    ok=True,
                    result={"hits": [{"chunk_id": "abc", "text": "..."}]},
                ),),
            ),
        )
        prompt = llm.calls[0]["messages"][0]["content"]
        assert "{{QUERY}}" not in prompt
        assert "{{INTENT}}" not in prompt
        assert "{{TOOL_RESULTS}}" not in prompt
        assert "{{CHART_PLACEHOLDERS}}" not in prompt
        assert "2025 跨境电商政策" in prompt
        assert "scenario_1" in prompt
        assert "search_chunks_by_semantic" in prompt

    def test_no_charts_renders_explicit_no_chart_note(self, seeded_session):
        llm = _ScriptedLLM("ok")
        composer = MDComposerV2(llm_client=llm)
        composer.compose(
            seeded_session,
            query="q",
            dispatch_result=_dispatch(),
        )
        prompt = llm.calls[0]["messages"][0]["content"]
        assert "本次无 chart 数据" in prompt

    def test_registered_charts_listed_for_llm(self, seeded_session):
        reg = ChartRegistry()
        chart_id = reg.register(
            tool_call_id="tool-1",
            payload=_sample_chart(),
        )
        llm = _ScriptedLLM(f"结果 [[CHART:{chart_id}]]")
        composer = MDComposerV2(llm_client=llm)
        composer.compose(
            seeded_session,
            query="q",
            dispatch_result=_dispatch(chart_registry=reg),
        )
        prompt = llm.calls[0]["messages"][0]["content"]
        assert chart_id in prompt

    def test_failed_tool_result_surfaced_in_prompt(self, seeded_session):
        llm = _ScriptedLLM("ok")
        composer = MDComposerV2(llm_client=llm)
        composer.compose(
            seeded_session,
            query="q",
            dispatch_result=_dispatch(
                tool_results=(ToolResult(
                    tool_call_id="bad",
                    name="internal.search_chunks_by_semantic",
                    arguments={"query": "q"},
                    ok=False,
                    error="RuntimeError: db down",
                ),),
            ),
        )
        prompt = llm.calls[0]["messages"][0]["content"]
        assert "db down" in prompt
        assert '"ok": false' in prompt


# ---------------------------------------------------------------------------
# Happy path — no charts
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_llm_output_flows_through_unchanged_when_no_charts(
        self, seeded_session,
    ):
        raw = "# 结果\n\n1. 第一条\n2. 第二条"
        llm = _ScriptedLLM(raw)
        composer = MDComposerV2(llm_client=llm)
        result = composer.compose(
            seeded_session,
            query="q",
            dispatch_result=_dispatch(),
        )
        assert result.fallback_reason is None
        assert result.markdown == raw
        assert result.raw_markdown == raw
        assert result.chart_hallucination_ids == []
        assert result.chart_unused_ids == []

    def test_generated_ratio_reflects_warning_block_share(self, seeded_session):
        # Half the answer is a `> ⚠️ ...` block.
        raw = (
            "真实数据段落。\n"
            "> ⚠️ 以下为模型推断内容，未匹配到平台资产\n"
            "> 推断段一\n"
            "> 推断段二\n"
        )
        llm = _ScriptedLLM(raw)
        composer = MDComposerV2(llm_client=llm)
        result = composer.compose(
            seeded_session,
            query="q",
            dispatch_result=_dispatch(),
        )
        assert result.fallback_reason is None
        assert 0.3 < result.generated_ratio < 0.9


def test_task_procedure_uses_all_ordered_context_steps_without_llm(seeded_session):
    llm = _ScriptedLLM("This response must not be used")
    composer = MDComposerV2(llm_client=llm)
    result = composer.compose(
        seeded_session,
        query="市场数据采集流程",
        dispatch_result=_dispatch(
            tool_results=(ToolResult(
                tool_call_id="task-steps",
                name="internal.search_chunks_by_semantic",
                arguments={"query": "市场数据采集流程"},
                ok=True,
                result={"answer_contexts": [{
                    "kind": "task_context",
                    "normalized_ref_id": "ref-market",
                    "title": "工作任务一 市场数据采集",
                    "chunks": [
                        {"step_no": 1, "task_title": "子任务一", "chunk_id": "c1", "locator": {"page": 1}, "content": "确定采集指标"},
                        {"step_no": 2, "task_title": "子任务一", "chunk_id": "c2", "locator": {"page": 2}, "content": "确定数据来源"},
                        {"step_no": 1, "task_title": "子任务二", "chunk_id": "c3", "locator": {"page": 3}, "content": "采集竞争对手数据"},
                    ],
                }]},
            ),),
        ),
    )

    assert llm.calls == []
    assert "### 子任务一" in result.markdown
    assert "### 子任务二" in result.markdown
    assert "确定采集指标" in result.markdown
    assert "确定数据来源" in result.markdown
    assert "采集竞争对手数据" in result.markdown
    assert "`ref-market` / `c3`" in result.markdown
    assert "其余步骤暂无" not in result.markdown


def test_section_classification_uses_all_context_chunks_without_llm(seeded_session):
    llm = _ScriptedLLM("This response must not be used")
    composer = MDComposerV2(llm_client=llm)
    result = composer.compose(
        seeded_session,
        query="短视频平台的类型",
        dispatch_result=_dispatch(
            tool_results=(ToolResult(
                tool_call_id="section-types",
                name="internal.search_chunks_by_semantic",
                arguments={"query": "短视频平台的类型"},
                ok=True,
                result={"answer_contexts": [{
                    "kind": "section_context",
                    "normalized_ref_id": "ref-short-video",
                    "title": "一、短视频平台的类型",
                    "chunks": [
                        {"chunk_id": "c1", "locator": {"page": 1}, "content": "短视频平台可分为以下四种。"},
                        {"chunk_id": "c2", "locator": {"page": 2}, "content": "社交媒体类短视频平台。"},
                        {"chunk_id": "c3", "locator": {"page": 3}, "content": "新闻资讯类短视频平台。"},
                        {"chunk_id": "c4", "locator": {"page": 4}, "content": "电商推广类短视频平台。"},
                        {"chunk_id": "c5", "locator": {"page": 5}, "content": "垂直领域类短视频平台。"},
                    ],
                }]},
            ),),
        ),
    )

    assert llm.calls == []
    assert "社交媒体类短视频平台" in result.markdown
    assert "新闻资讯类短视频平台" in result.markdown
    assert "电商推广类短视频平台" in result.markdown
    assert "垂直领域类短视频平台" in result.markdown
    assert "`ref-short-video` / `c5`" in result.markdown


def test_section_context_restores_locator_subheadings_without_llm(seeded_session):
    llm = _ScriptedLLM("This response must not be used")
    result = MDComposerV2(llm_client=llm).compose(
        seeded_session,
        query="短视频账号定位的作用",
        dispatch_result=_dispatch(
            tool_results=(ToolResult(
                tool_call_id="account-positioning",
                name="internal.search_chunks_by_semantic",
                arguments={"query": "短视频账号定位的作用"},
                ok=True,
                result={"answer_contexts": [{
                    "kind": "section_context",
                    "normalized_ref_id": "ref-account",
                    "title": "一、短视频账号定位的作用",
                    "chunks": [
                        {"chunk_id": "c1", "locator": {"heading_path": [{"title": "一、短视频账号定位的作用"}]}, "content": "账号定位具有多项作用。"},
                        {"chunk_id": "c2", "locator": {"heading_path": [{"title": "1. 聚焦目标用户"}]}, "content": "账号定位能够使目标受众更加精准。"},
                    ],
                }]},
            ),),
        ),
    )

    assert llm.calls == []
    assert "### 1. 聚焦目标用户" in result.markdown
    assert "账号定位能够使目标受众更加精准" in result.markdown


# ---------------------------------------------------------------------------
# Chart placeholder replacement
# ---------------------------------------------------------------------------


class TestChartReplacement:
    def test_registered_placeholder_swapped_for_fenced_block(
        self, seeded_session,
    ):
        reg = ChartRegistry()
        chart_id = reg.register(
            tool_call_id="tool-1", payload=_sample_chart(),
        )
        raw = f"# 图谱\n\n[[CHART:{chart_id}]]\n\n以上为结果。"
        llm = _ScriptedLLM(raw)
        composer = MDComposerV2(llm_client=llm)
        result = composer.compose(
            seeded_session,
            query="q",
            dispatch_result=_dispatch(chart_registry=reg),
        )
        assert result.fallback_reason is None
        assert "```chart:echarts" in result.markdown
        assert "新媒体运营" in result.markdown
        # Original placeholder replaced — not preserved verbatim.
        assert f"[[CHART:{chart_id}]]" not in result.markdown

    def test_hallucinated_placeholder_kept_verbatim_and_recorded(
        self, seeded_session,
    ):
        reg = ChartRegistry()
        raw = "结果 [[CHART:phantom-id:0]] 和更多内容"
        llm = _ScriptedLLM(raw)
        composer = MDComposerV2(llm_client=llm)
        result = composer.compose(
            seeded_session,
            query="q",
            dispatch_result=_dispatch(chart_registry=reg),
        )
        # Placeholder preserved so downstream review can spot the issue.
        assert "[[CHART:phantom-id:0]]" in result.markdown
        assert "phantom-id:0" in result.chart_hallucination_ids

    def test_unused_registered_chart_surfaces_in_unused_ids(
        self, seeded_session,
    ):
        reg = ChartRegistry()
        chart_id = reg.register(
            tool_call_id="tool-1", payload=_sample_chart(),
        )
        # LLM output makes no reference to any chart.
        raw = "# 回答\n\n此处仅文字，不引用图表。"
        llm = _ScriptedLLM(raw)
        composer = MDComposerV2(llm_client=llm)
        result = composer.compose(
            seeded_session,
            query="q",
            dispatch_result=_dispatch(chart_registry=reg),
        )
        assert chart_id in result.chart_unused_ids

    def test_mixed_registered_and_hallucinated_placeholders(
        self, seeded_session,
    ):
        reg = ChartRegistry()
        good_id = reg.register(
            tool_call_id="good", payload=_sample_chart(),
        )
        raw = (
            f"图1: [[CHART:{good_id}]]\n\n"
            f"图2: [[CHART:not-registered:0]]"
        )
        llm = _ScriptedLLM(raw)
        composer = MDComposerV2(llm_client=llm)
        result = composer.compose(
            seeded_session,
            query="q",
            dispatch_result=_dispatch(chart_registry=reg),
        )
        assert "```chart:echarts" in result.markdown
        assert "[[CHART:not-registered:0]]" in result.markdown
        assert result.chart_hallucination_ids == ["not-registered:0"]


# ---------------------------------------------------------------------------
# Fallbacks
# ---------------------------------------------------------------------------


class TestFallbacks:
    def test_missing_prompt_profile_returns_prompt_fallback(self, session):
        # No seed — profile lookup will raise LookupError.
        llm = _ScriptedLLM("wouldn't be called")
        composer = MDComposerV2(llm_client=llm)
        result = composer.compose(
            session,
            query="q",
            dispatch_result=_dispatch(),
        )
        assert result.fallback_reason == "prompt_profile_missing"
        assert "⚠️" in result.markdown
        assert llm.calls == []

    def test_llm_error_returns_llm_call_failed(self, seeded_session):
        llm = _ScriptedLLM(
            "",
            raise_error=LiteLLMCallError(
                "rate limit", LiteLLMErrorType.RATE_LIMIT,
            ),
        )
        composer = MDComposerV2(llm_client=llm)
        result = composer.compose(
            seeded_session,
            query="q",
            dispatch_result=_dispatch(),
        )
        assert result.fallback_reason == "llm_call_failed"
        assert "rate_limit" in result.warnings

    def test_empty_llm_output_returns_empty_fallback(self, seeded_session):
        llm = _ScriptedLLM("   \n\n   ")
        composer = MDComposerV2(llm_client=llm)
        result = composer.compose(
            seeded_session,
            query="q",
            dispatch_result=_dispatch(),
        )
        assert result.fallback_reason == "empty_llm_output"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestGeneratedRatio:
    def test_no_warning_block_returns_zero(self):
        assert _compute_generated_ratio("just regular text") == 0.0

    def test_all_warning_block_returns_one(self):
        text = "> ⚠️ 全部内容都是推断\n> 更多推断"
        assert _compute_generated_ratio(text) == pytest.approx(1.0, abs=0.05)

    def test_empty_string_returns_zero(self):
        assert _compute_generated_ratio("") == 0.0

    def test_regular_blockquote_without_warning_marker_not_counted(self):
        """> 段落 without the ⚠️ marker is a cited quote, not a
        generated wrapper — it must NOT count toward the ratio."""
        text = "> 这是引用段落而非推断内容\n\n真实数据段落。"
        assert _compute_generated_ratio(text) == 0.0


class TestSerialiseToolResults:
    def test_ok_result_includes_full_payload(self):
        rendered = _serialise_tool_results((ToolResult(
            tool_call_id="c1",
            name="internal.search_chunks_by_semantic",
            arguments={"query": "q"},
            ok=True,
            result={"hits": [{"chunk_id": "x"}]},
        ),))
        parsed = json.loads(rendered)
        # Successful entries omit the `ok` key (only failed ones set it
        # so LLM can quickly distinguish); the presence of `result` is
        # the affirmative signal.
        assert "ok" not in parsed[0]
        assert parsed[0]["result"] == {"hits": [{"chunk_id": "x"}]}

    def test_failed_result_marked_and_error_carried(self):
        rendered = _serialise_tool_results((ToolResult(
            tool_call_id="c1",
            name="internal.query_job_demand",
            arguments={"major": "x"},
            ok=False,
            error="RuntimeError: boom",
        ),))
        parsed = json.loads(rendered)
        assert parsed[0]["ok"] is False
        assert "boom" in parsed[0]["error"]
        assert "result" not in parsed[0]

    def test_chart_ids_carried_when_present(self):
        rendered = _serialise_tool_results((ToolResult(
            tool_call_id="c1",
            name="internal.query_capability_graph_by_major",
            arguments={"major_name": "x", "build_type": "ability_analysis"},
            ok=True,
            result={"summary": "ok"},
            chart_ids=("c1:0",),
        ),))
        parsed = json.loads(rendered)
        assert parsed[0]["chart_ids"] == ["c1:0"]
