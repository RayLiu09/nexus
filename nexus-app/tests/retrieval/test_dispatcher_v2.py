"""B4 (§10 阶段 B) — DispatcherV2 tests.

Covers:
* Short-circuit paths (unknown intent, scenario_5 template, unknown scenario id).
* Happy path (tool_call → validation → parallel execution → results).
* Validation retry (first invalid → second valid → success).
* Fallback paths (no tool_call, param_validation_failed after retry,
  llm_call_failed, no_tools_registered, tool_execution_failed).
* scenario_3 dual-path warning surfaces when the LLM only calls one tool.
* Chart registration flow — executor writes into shared ChartRegistry
  and the returned ``ToolResult.chart_ids`` picks up the new ids.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMCallSummary,
    LiteLLMErrorType,
    ToolCall,
    ToolCallingResult,
)
from nexus_app.retrieval.chart_adapter import (
    ChartMeta,
    ChartNode,
    ChartPayload,
    ChartRegistry,
    make_chart_id,
)
from nexus_app.retrieval.dispatcher_v2 import (
    DispatcherV2,
    DispatchResult,
    ToolExecutorRegistry,
    ToolInvocation,
    _validate_arguments,
)
from nexus_app.retrieval.tools_registry import get_default_tool_registry


# ---------------------------------------------------------------------------
# _validate_arguments — pure function
# ---------------------------------------------------------------------------


class TestValidateArguments:
    def test_missing_required_returns_error(self):
        schema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }
        err = _validate_arguments(schema, {})
        assert err is not None
        assert "query" in err

    def test_null_required_treated_as_missing(self):
        schema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }
        err = _validate_arguments(schema, {"query": None})
        assert err is not None

    def test_const_mismatch_returns_error(self):
        schema = {
            "type": "object",
            "properties": {
                "build_type": {"type": "string", "const": "teaching_standard"},
            },
            "required": ["build_type"],
        }
        err = _validate_arguments(schema, {"build_type": "ability_analysis"})
        assert err is not None
        assert "const" in err

    def test_const_match_ok(self):
        schema = {
            "type": "object",
            "properties": {
                "build_type": {"type": "string", "const": "teaching_standard"},
            },
            "required": ["build_type"],
        }
        assert _validate_arguments(schema, {"build_type": "teaching_standard"}) is None

    def test_enum_membership(self):
        schema = {
            "type": "object",
            "properties": {"kb": {"type": "string", "enum": ["a", "b"]}},
        }
        assert _validate_arguments(schema, {"kb": "a"}) is None
        assert _validate_arguments(schema, {"kb": "c"}) is not None

    def test_type_mismatch(self):
        schema = {
            "type": "object",
            "properties": {"top_k": {"type": "integer"}},
        }
        assert _validate_arguments(schema, {"top_k": 5}) is None
        err = _validate_arguments(schema, {"top_k": "5"})
        assert err is not None
        assert "integer" in err

    def test_boolean_not_accepted_as_integer(self):
        """JSON Schema treats bool and int as disjoint even though
        Python's isinstance(True, int) is True."""
        schema = {
            "type": "object",
            "properties": {"top_k": {"type": "integer"}},
        }
        err = _validate_arguments(schema, {"top_k": True})
        assert err is not None

    def test_pattern_check(self):
        schema = {
            "type": "object",
            "properties": {
                "major_code": {"type": "string", "pattern": r"^\d{4,6}$"},
            },
        }
        assert _validate_arguments(schema, {"major_code": "5301"}) is None
        assert _validate_arguments(schema, {"major_code": "ABC"}) is not None

    def test_any_of_alternative_satisfied(self):
        schema = {
            "type": "object",
            "properties": {
                "major_name": {"type": "string"},
                "major_code": {"type": "string"},
                "build_type": {"type": "string"},
            },
            "required": ["build_type"],
            "anyOf": [
                {"required": ["major_name"]},
                {"required": ["major_code"]},
            ],
        }
        assert _validate_arguments(
            schema,
            {"build_type": "teaching_standard", "major_code": "5301"},
        ) is None

    def test_any_of_neither_satisfied(self):
        schema = {
            "type": "object",
            "properties": {
                "major_name": {"type": "string"},
                "major_code": {"type": "string"},
                "build_type": {"type": "string"},
            },
            "required": ["build_type"],
            "anyOf": [
                {"required": ["major_name"]},
                {"required": ["major_code"]},
            ],
        }
        err = _validate_arguments(
            schema,
            {"build_type": "teaching_standard"},
        )
        assert err is not None
        assert "anyOf" in err

    def test_extra_field_ignored(self):
        """LLM hallucinated an extra field — executor drops it, validator
        is tolerant to avoid noisy retries."""
        schema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }
        assert _validate_arguments(
            schema,
            {"query": "q", "made_up": "shouldn't leak"},
        ) is None


# ---------------------------------------------------------------------------
# Fake LLM + fake executors
# ---------------------------------------------------------------------------


def _summary() -> LiteLLMCallSummary:
    return LiteLLMCallSummary(
        model_alias="primary-llm",
        request_id="fake",
        latency_ms=1.0,
        status="success",
        input_hash="hash",
    )


def _tc_result(
    tool_calls: list[ToolCall] | None = None,
    *,
    content: str = "",
    finish_reason: str | None = "tool_calls",
) -> ToolCallingResult:
    return ToolCallingResult(
        content=content,
        tool_calls=tool_calls or [],
        finish_reason=finish_reason,
        summary=_summary(),
    )


class _ScriptedToolLLM:
    """LLM stub that returns a queued sequence of ToolCallingResults.

    Raises ``StopIteration`` if the dispatcher calls it more times than
    scripted — surfaces retry bugs immediately.
    """

    def __init__(
        self,
        responses: list[ToolCallingResult | LiteLLMCallError],
    ) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def call(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def call_with_tools(self, model_alias, messages, **kwargs):
        self.calls.append({
            "model_alias": model_alias,
            "messages": messages,
            "kwargs": kwargs,
        })
        if not self._responses:
            raise AssertionError("LLM called more times than scripted")
        nxt = self._responses.pop(0)
        if isinstance(nxt, LiteLLMCallError):
            raise nxt
        return nxt


def _fake_executor(payload_map: dict[str, dict]):
    """Return an executor callable that responds by tool_call_id."""

    def _run(*, session, arguments, tool_call_id, chart_registry):
        return payload_map.get(tool_call_id, {"echo": arguments})

    return _run


def _chart_registering_executor(chart_index: int = 0):
    def _run(*, session, arguments, tool_call_id, chart_registry):
        chart_id = chart_registry.register(
            tool_call_id=tool_call_id,
            payload=ChartPayload(
                nodes=[ChartNode(id="n1", name="X", category="position")],
                edges=[],
                meta=ChartMeta(title="fake"),
            ),
            chart_index=chart_index,
        )
        return {"chart_id": chart_id, "summary": "ok"}

    return _run


def _boom_executor(*, session, arguments, tool_call_id, chart_registry):
    raise RuntimeError("intentional test failure")


@pytest.fixture()
def registry():
    return get_default_tool_registry()


# ---------------------------------------------------------------------------
# Short-circuit paths
# ---------------------------------------------------------------------------


class TestShortCircuits:
    def test_unknown_intent_returns_fallback(self, session):
        dispatcher = DispatcherV2(
            llm_client=_ScriptedToolLLM([]),
            executor_registry=ToolExecutorRegistry(),
        )
        result = dispatcher.dispatch(
            session, query="q", intent="unknown",
            extracted_params={}, model_alias="primary-llm",
        )
        assert result.fallback_reason == "unknown_intent"
        assert result.tool_results == ()

    def test_scenario_5_returns_template_fallback(self, session):
        dispatcher = DispatcherV2(
            llm_client=_ScriptedToolLLM([]),
            executor_registry=ToolExecutorRegistry(),
        )
        result = dispatcher.dispatch(
            session, query="人才培养方案", intent="scenario_5",
            extracted_params={"major_name": "跨境电商"},
            model_alias="primary-llm",
        )
        assert result.fallback_reason == "scenario_5_template"

    def test_unknown_scenario_id_treated_as_unknown_intent(self, session):
        dispatcher = DispatcherV2(
            llm_client=_ScriptedToolLLM([]),
            executor_registry=ToolExecutorRegistry(),
        )
        result = dispatcher.dispatch(
            session, query="q", intent="scenario_99",
            extracted_params={}, model_alias="primary-llm",
        )
        assert result.fallback_reason == "unknown_intent"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_single_tool_call_executes_and_returns_result(self, session):
        tc = ToolCall(
            id="call-1",
            name="internal.search_chunks_by_semantic",
            arguments='{"query": "跨境电商 2025 政策", "kb": "industry_research_kb"}',
        )
        llm = _ScriptedToolLLM([_tc_result([tc])])
        exec_reg = ToolExecutorRegistry()
        exec_reg.register(
            "internal.search_chunks_by_semantic",
            _fake_executor({"call-1": {"hits": [{"chunk_id": "c1"}]}}),
        )
        dispatcher = DispatcherV2(
            llm_client=llm, executor_registry=exec_reg,
        )
        result = dispatcher.dispatch(
            session,
            query="跨境电商 2025 政策",
            intent="scenario_1",
            extracted_params={"query": "跨境电商 2025 政策"},
            model_alias="primary-llm",
        )
        assert result.fallback_reason is None
        assert len(result.tool_results) == 1
        assert result.tool_results[0].ok is True
        assert result.tool_results[0].result == {"hits": [{"chunk_id": "c1"}]}
        assert result.invoked_tool_names == ["internal.search_chunks_by_semantic"]

    def test_multiple_tool_calls_run_in_parallel(self, session):
        tc1 = ToolCall(
            id="call-1",
            name="internal.query_capability_graph_by_major",
            arguments='{"major_name": "跨境电商", "build_type": "teaching_standard"}',
        )
        tc2 = ToolCall(
            id="call-2",
            name="internal.search_chunks_by_semantic",
            arguments=(
                '{"query": "跨境电商 培养目标", '
                '"kb": "course_standard_authoring_process", '
                '"outline_node": "培养目标"}'
            ),
        )
        llm = _ScriptedToolLLM([_tc_result([tc1, tc2])])
        exec_reg = ToolExecutorRegistry()
        exec_reg.register(
            "internal.query_capability_graph_by_major",
            _fake_executor({"call-1": {"nodes": [], "edges": []}}),
        )
        exec_reg.register(
            "internal.search_chunks_by_semantic",
            _fake_executor({"call-2": {"hits": []}}),
        )
        dispatcher = DispatcherV2(
            llm_client=llm, executor_registry=exec_reg,
        )
        result = dispatcher.dispatch(
            session,
            query="跨境电商专业教学标准",
            intent="scenario_3",
            extracted_params={"major_name": "跨境电商"},
            model_alias="primary-llm",
        )
        assert result.fallback_reason is None
        assert len(result.tool_results) == 2
        assert all(r.ok for r in result.tool_results)
        # scenario_3 with both tools present → no warning
        assert result.warnings == ()

    def test_extracted_params_appear_in_llm_messages(self, session):
        tc = ToolCall(
            id="call-1",
            name="internal.search_chunks_by_semantic",
            arguments='{"query": "q", "kb": "industry_research_kb"}',
        )
        llm = _ScriptedToolLLM([_tc_result([tc])])
        exec_reg = ToolExecutorRegistry()
        exec_reg.register(
            "internal.search_chunks_by_semantic",
            _fake_executor({"call-1": {"ok": True}}),
        )
        dispatcher = DispatcherV2(
            llm_client=llm, executor_registry=exec_reg,
        )
        dispatcher.dispatch(
            session,
            query="test query",
            intent="scenario_1",
            extracted_params={"query": "test query", "top_k": 5},
            model_alias="primary-llm",
        )
        prompt = llm.calls[0]["messages"][0]["content"]
        assert "test query" in prompt
        assert "scenario_1" in prompt
        assert "top_k" in prompt


# ---------------------------------------------------------------------------
# Validation retry
# ---------------------------------------------------------------------------


class TestValidationRetry:
    def test_first_invalid_second_valid_succeeds(self, session):
        # scenario_1 requires `query`. First response omits it → retry.
        bad = ToolCall(
            id="call-1",
            name="internal.search_chunks_by_semantic",
            arguments='{"kb": "industry_research_kb"}',  # missing `query`
        )
        good = ToolCall(
            id="call-2",
            name="internal.search_chunks_by_semantic",
            arguments='{"query": "q", "kb": "industry_research_kb"}',
        )
        llm = _ScriptedToolLLM([_tc_result([bad]), _tc_result([good])])
        exec_reg = ToolExecutorRegistry()
        exec_reg.register(
            "internal.search_chunks_by_semantic",
            _fake_executor({"call-2": {"hits": [1]}}),
        )
        dispatcher = DispatcherV2(
            llm_client=llm, executor_registry=exec_reg,
        )
        result = dispatcher.dispatch(
            session, query="q", intent="scenario_1",
            extracted_params={"query": "q"},
            model_alias="primary-llm",
        )
        assert result.fallback_reason is None
        assert len(llm.calls) == 2, "retry must have fired"
        # Retry prompt should mention what went wrong.
        assert "validation" in llm.calls[1]["messages"][-1]["content"].lower()

    def test_both_attempts_invalid_falls_back(self, session):
        bad1 = ToolCall(
            id="a",
            name="internal.search_chunks_by_semantic",
            arguments='{}',
        )
        bad2 = ToolCall(
            id="b",
            name="internal.search_chunks_by_semantic",
            arguments='{"kb": "industry_research_kb"}',
        )
        llm = _ScriptedToolLLM([_tc_result([bad1]), _tc_result([bad2])])
        dispatcher = DispatcherV2(
            llm_client=llm, executor_registry=ToolExecutorRegistry(),
        )
        result = dispatcher.dispatch(
            session, query="q", intent="scenario_1",
            extracted_params={}, model_alias="primary-llm",
        )
        assert result.fallback_reason == "param_validation_failed"
        assert result.tool_invocations
        assert result.tool_invocations[0].validation_error is not None

    def test_unknown_tool_name_treated_as_validation_error(self, session):
        tc = ToolCall(
            id="a",
            name="internal.made_up_tool",
            arguments='{"x": 1}',
        )
        # Second attempt also invalid so we don't need to script a fix
        tc2 = ToolCall(
            id="b",
            name="internal.also_made_up",
            arguments='{"x": 1}',
        )
        llm = _ScriptedToolLLM([_tc_result([tc]), _tc_result([tc2])])
        dispatcher = DispatcherV2(
            llm_client=llm, executor_registry=ToolExecutorRegistry(),
        )
        result = dispatcher.dispatch(
            session, query="q", intent="scenario_1",
            extracted_params={}, model_alias="primary-llm",
        )
        assert result.fallback_reason == "param_validation_failed"

    def test_arguments_not_json_treated_as_validation_error(self, session):
        tc = ToolCall(
            id="a",
            name="internal.search_chunks_by_semantic",
            arguments='not-json',
        )
        tc2 = ToolCall(
            id="b",
            name="internal.search_chunks_by_semantic",
            arguments='also-broken',
        )
        llm = _ScriptedToolLLM([_tc_result([tc]), _tc_result([tc2])])
        dispatcher = DispatcherV2(
            llm_client=llm, executor_registry=ToolExecutorRegistry(),
        )
        result = dispatcher.dispatch(
            session, query="q", intent="scenario_1",
            extracted_params={}, model_alias="primary-llm",
        )
        assert result.fallback_reason == "param_validation_failed"


# ---------------------------------------------------------------------------
# LLM-side fallbacks
# ---------------------------------------------------------------------------


class TestLLMFallbacks:
    def test_no_tool_call_returns_no_tool_call(self, session):
        llm = _ScriptedToolLLM([_tc_result([], content="I don't know")])
        dispatcher = DispatcherV2(
            llm_client=llm, executor_registry=ToolExecutorRegistry(),
        )
        result = dispatcher.dispatch(
            session, query="q", intent="scenario_1",
            extracted_params={}, model_alias="primary-llm",
        )
        assert result.fallback_reason == "no_tool_call"
        # Design red-line: no retry when LLM chose not to invoke a tool.
        assert len(llm.calls) == 1

    def test_llm_error_first_attempt_returns_llm_call_failed(self, session):
        llm = _ScriptedToolLLM([
            LiteLLMCallError("rate limit", LiteLLMErrorType.RATE_LIMIT),
        ])
        dispatcher = DispatcherV2(
            llm_client=llm, executor_registry=ToolExecutorRegistry(),
        )
        result = dispatcher.dispatch(
            session, query="q", intent="scenario_1",
            extracted_params={}, model_alias="primary-llm",
        )
        assert result.fallback_reason == "llm_call_failed"
        assert "rate_limit" in result.warnings

    def test_llm_error_on_retry_returns_llm_call_failed(self, session):
        bad = ToolCall(
            id="a",
            name="internal.search_chunks_by_semantic",
            arguments='{}',
        )
        llm = _ScriptedToolLLM([
            _tc_result([bad]),
            LiteLLMCallError("boom", LiteLLMErrorType.SERVER_ERROR),
        ])
        dispatcher = DispatcherV2(
            llm_client=llm, executor_registry=ToolExecutorRegistry(),
        )
        result = dispatcher.dispatch(
            session, query="q", intent="scenario_1",
            extracted_params={}, model_alias="primary-llm",
        )
        assert result.fallback_reason == "llm_call_failed"

    def test_retry_no_tool_call_returns_no_tool_call(self, session):
        bad = ToolCall(
            id="a",
            name="internal.search_chunks_by_semantic",
            arguments='{}',
        )
        llm = _ScriptedToolLLM([
            _tc_result([bad]),
            _tc_result([], content="giving up"),
        ])
        dispatcher = DispatcherV2(
            llm_client=llm, executor_registry=ToolExecutorRegistry(),
        )
        result = dispatcher.dispatch(
            session, query="q", intent="scenario_1",
            extracted_params={}, model_alias="primary-llm",
        )
        assert result.fallback_reason == "no_tool_call"


# ---------------------------------------------------------------------------
# Executor-side outcomes
# ---------------------------------------------------------------------------


class TestExecutorOutcomes:
    def test_no_executor_registered_marks_result_not_ok(self, session):
        tc = ToolCall(
            id="a",
            name="internal.search_chunks_by_semantic",
            arguments='{"query": "q", "kb": "industry_research_kb"}',
        )
        llm = _ScriptedToolLLM([_tc_result([tc])])
        dispatcher = DispatcherV2(
            llm_client=llm, executor_registry=ToolExecutorRegistry(),
        )
        result = dispatcher.dispatch(
            session, query="q", intent="scenario_1",
            extracted_params={"query": "q"},
            model_alias="primary-llm",
        )
        # All executors missing → dispatcher fallbacks so caller knows
        # there's nothing to compose.
        assert result.fallback_reason == "no_tools_registered"
        assert result.tool_results[0].ok is False

    def test_executor_exception_marks_result_not_ok(self, session):
        # Both tools live in scenario_2 — job_demand and capability_graph.
        tc1 = ToolCall(
            id="ok",
            name="internal.query_job_demand",
            arguments='{"major": "跨境电商"}',
        )
        tc2 = ToolCall(
            id="boom",
            name="internal.query_capability_graph_by_major",
            arguments='{"major_name": "x", "build_type": "ability_analysis"}',
        )
        llm = _ScriptedToolLLM([_tc_result([tc1, tc2])])
        exec_reg = ToolExecutorRegistry()
        exec_reg.register(
            "internal.query_job_demand",
            _fake_executor({"ok": {"records": []}}),
        )
        exec_reg.register(
            "internal.query_capability_graph_by_major",
            _boom_executor,
        )
        dispatcher = DispatcherV2(
            llm_client=llm, executor_registry=exec_reg,
        )
        result = dispatcher.dispatch(
            session, query="q", intent="scenario_2",
            extracted_params={}, model_alias="primary-llm",
        )
        # At least one succeeded → dispatcher does NOT fallback, but
        # the failed executor result is preserved with error string.
        assert result.fallback_reason is None
        by_id = {r.tool_call_id: r for r in result.tool_results}
        assert by_id["ok"].ok is True
        assert by_id["boom"].ok is False
        assert "RuntimeError" in by_id["boom"].error

    def test_chart_registration_surfaces_on_result(self, session):
        tc = ToolCall(
            id="graph-call",
            name="internal.query_capability_graph_by_major",
            arguments='{"major_name": "跨境电商", "build_type": "ability_analysis"}',
        )
        llm = _ScriptedToolLLM([_tc_result([tc])])
        exec_reg = ToolExecutorRegistry()
        exec_reg.register(
            "internal.query_capability_graph_by_major",
            _chart_registering_executor(chart_index=0),
        )
        dispatcher = DispatcherV2(
            llm_client=llm, executor_registry=exec_reg,
        )
        result = dispatcher.dispatch(
            session, query="q", intent="scenario_2",
            extracted_params={}, model_alias="primary-llm",
        )
        assert result.fallback_reason is None
        expected = make_chart_id("graph-call", 0)
        assert expected in result.tool_results[0].chart_ids
        assert expected in result.chart_registry.registered_ids()


# ---------------------------------------------------------------------------
# scenario_3 dual-path soft check
# ---------------------------------------------------------------------------


class TestScenario3DualPath:
    def test_only_one_tool_called_surfaces_warning(self, session):
        # scenario_3 expects both tools; we script only one.
        tc = ToolCall(
            id="a",
            name="internal.query_capability_graph_by_major",
            arguments='{"major_name": "跨境电商", "build_type": "teaching_standard"}',
        )
        llm = _ScriptedToolLLM([_tc_result([tc])])
        exec_reg = ToolExecutorRegistry()
        exec_reg.register(
            "internal.query_capability_graph_by_major",
            _fake_executor({"a": {"nodes": []}}),
        )
        dispatcher = DispatcherV2(
            llm_client=llm, executor_registry=exec_reg,
        )
        result = dispatcher.dispatch(
            session, query="教学标准", intent="scenario_3",
            extracted_params={"major_name": "跨境电商"},
            model_alias="primary-llm",
        )
        # Soft check: still succeeds but flags the missing tool.
        assert result.fallback_reason is None
        assert any(
            w.startswith("scenario_3_dual_path_missing")
            for w in result.warnings
        )
