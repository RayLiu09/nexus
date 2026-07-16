"""A0 (§10 阶段 A + §1.11 决策 #4) — LiteLLM function calling / tool use.

Covers the 5 dispatcher-facing scenarios enumerated in the task
package's A0 DoD:

1. Single tool call, successful decode of arguments
2. Multiple parallel tool calls in one response
3. Model returned zero tool_calls (finish_reason=stop) → empty list,
   fallback signal delivered to dispatcher
4. Malformed tool payload (missing function) — silently dropped
5. Underlying API error surfaces as LiteLLMCallError

Plus:
* `FakeLiteLLMClient.call_with_tools()` default response,
  `tool_calls_override` behaviour, and empty-tools smoke.
* Backwards-compat: existing `call()` signature unchanged (regression
  smoke against the `FakeLiteLLMClient` demo payload).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nexus_app.ai_governance.litellm_client import (
    FakeLiteLLMClient,
    LiteLLMCallError,
    LiteLLMCallSummary,
    LiteLLMConfig,
    LiteLLMErrorType,
    RealLiteLLMClient,
    ToolCall,
    ToolCallingResult,
)


# ---------------------------------------------------------------------------
# Fixture: real client with the OpenAI SDK replaced by a MagicMock so we
# don't hit the network.
# ---------------------------------------------------------------------------


def _make_real_client(response_mock) -> RealLiteLLMClient:
    """Build a `RealLiteLLMClient` whose OpenAI SDK is fully mocked.

    The constructor tries to `from openai import ...` which is a real
    dependency in this project — so we let that succeed, then swap
    `_client` after construction.
    """
    cfg = LiteLLMConfig(base_url="http://fake", api_key_ref="test")
    client = RealLiteLLMClient(cfg, api_key="unused")
    mock_openai = MagicMock()
    mock_openai.chat.completions.create.return_value = response_mock
    client._client = mock_openai
    return client


def _resp(
    *,
    tool_calls: list[SimpleNamespace] | None = None,
    finish_reason: str = "tool_calls",
    content: str | None = None,
    request_id: str = "req-abc",
) -> SimpleNamespace:
    """Build the shape returned by the OpenAI SDK's chat.completions.create."""
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(id=request_id, choices=[choice])


def _tc(id_: str, name: str, arguments: str) -> SimpleNamespace:
    """OpenAI SDK ToolCall dataclass shape — `id` + `function.{name,arguments}`."""
    return SimpleNamespace(
        id=id_,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


# ---------------------------------------------------------------------------
# RealLiteLLMClient.call_with_tools
# ---------------------------------------------------------------------------


class TestRealClientCallWithTools:
    def test_single_tool_call_returns_parsed_arguments(self):
        client = _make_real_client(_resp(
            tool_calls=[_tc("tc-1", "internal.query_x", '{"query":"foo"}')],
            finish_reason="tool_calls",
        ))
        result = client.call_with_tools(
            "primary-llm",
            [{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "internal.query_x"}}],
        )
        assert isinstance(result, ToolCallingResult)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "tc-1"
        assert result.tool_calls[0].name == "internal.query_x"
        # `arguments` stays a raw string — Pydantic parsing is dispatcher-side.
        assert result.tool_calls[0].arguments == '{"query":"foo"}'
        assert result.finish_reason == "tool_calls"
        assert result.summary.status == "success"

    def test_multiple_parallel_tool_calls_returned_in_order(self):
        client = _make_real_client(_resp(
            tool_calls=[
                _tc("tc-1", "internal.a", '{}'),
                _tc("tc-2", "internal.b", '{}'),
                _tc("tc-3", "internal.c", '{}'),
            ],
        ))
        result = client.call_with_tools(
            "primary-llm",
            [{"role": "user", "content": "hi"}],
            tools=[{"function": {"name": "internal.a"}}],
        )
        assert [tc.name for tc in result.tool_calls] == [
            "internal.a", "internal.b", "internal.c",
        ]

    def test_zero_tool_calls_returns_empty_list_and_stop_reason(self):
        """§1.11 决策 #4 — model chose not to invoke any tool. The client
        does NOT retry; the caller falls back to `unknown`."""
        client = _make_real_client(_resp(
            tool_calls=None,
            finish_reason="stop",
            content="Sorry, I don't have enough info.",
        ))
        result = client.call_with_tools(
            "primary-llm",
            [{"role": "user", "content": "hi"}],
            tools=[{"function": {"name": "any"}}],
        )
        assert result.tool_calls == []
        assert result.finish_reason == "stop"
        assert result.content.startswith("Sorry")

    def test_malformed_tool_payload_missing_function_is_dropped(self):
        """Defence-in-depth against shape drift — a tool_call entry that
        lacks `function` shouldn't crash the parser."""
        client = _make_real_client(_resp(
            tool_calls=[
                SimpleNamespace(id="broken", function=None),
                _tc("tc-2", "internal.b", '{}'),
            ],
        ))
        result = client.call_with_tools(
            "primary-llm",
            [{"role": "user", "content": "hi"}],
            tools=[{"function": {"name": "internal.b"}}],
        )
        # Broken entry silently dropped; well-formed one survives.
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "tc-2"

    def test_underlying_api_error_wrapped_as_call_error(self):
        cfg = LiteLLMConfig(base_url="http://fake", api_key_ref="test")
        client = RealLiteLLMClient(cfg, api_key="unused")
        boom = MagicMock()
        boom.chat.completions.create.side_effect = RuntimeError("boom")
        client._client = boom
        with pytest.raises(LiteLLMCallError) as excinfo:
            client.call_with_tools(
                "primary-llm",
                [{"role": "user", "content": "hi"}],
                tools=[{"function": {"name": "any"}}],
            )
        assert "call_with_tools failed" in str(excinfo.value)


# ---------------------------------------------------------------------------
# FakeLiteLLMClient.call_with_tools
# ---------------------------------------------------------------------------


class TestFakeClientCallWithTools:
    def test_default_picks_first_tool_with_empty_args(self):
        fake = FakeLiteLLMClient()
        result = fake.call_with_tools(
            "primary-llm",
            messages=[{"role": "user", "content": "hi"}],
            tools=[
                {"type": "function", "function": {"name": "internal.a"}},
                {"type": "function", "function": {"name": "internal.b"}},
            ],
        )
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "internal.a"
        assert result.tool_calls[0].arguments == "{}"
        assert result.finish_reason == "tool_calls"

    def test_empty_tools_list_yields_zero_tool_calls_stop_reason(self):
        fake = FakeLiteLLMClient()
        result = fake.call_with_tools(
            "primary-llm",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
        )
        assert result.tool_calls == []
        assert result.finish_reason == "stop"

    def test_tool_calls_override_delivered_verbatim(self):
        """A dispatcher test wants to simulate a specific model choice
        (e.g. "picked internal.query_job_demand with major=电子商务");
        `tool_calls_override` provides that path without subclassing."""
        override = [
            ToolCall(id="tc-x", name="internal.query_job_demand",
                     arguments='{"major":"电子商务"}'),
        ]
        fake = FakeLiteLLMClient(tool_calls_override=override)
        result = fake.call_with_tools(
            "primary-llm", messages=[], tools=[{"function": {"name": "unused"}}],
        )
        assert result.tool_calls == override

    def test_empty_override_simulates_unknown_fallback_signal(self):
        """§1.11 决策 #4 dispatcher test — set override=[] to simulate
        the model returning zero tool_calls even when tools were
        offered."""
        fake = FakeLiteLLMClient(tool_calls_override=[])
        result = fake.call_with_tools(
            "primary-llm",
            messages=[],
            tools=[{"function": {"name": "internal.a"}}],
        )
        assert result.tool_calls == []
        assert result.finish_reason == "stop"

    def test_custom_finish_reason_override(self):
        fake = FakeLiteLLMClient(
            tool_calls_override=[],
            finish_reason_with_tools="length",
        )
        result = fake.call_with_tools("m", messages=[], tools=[])
        assert result.finish_reason == "length"


# ---------------------------------------------------------------------------
# Backwards compat — existing call() must not have changed shape.
# ---------------------------------------------------------------------------


def test_fake_client_call_backwards_compat():
    fake = FakeLiteLLMClient()
    content, summary = fake.call("m", messages=[{"role": "user", "content": "x"}])
    # Content is JSON with the historical "classification"/"level" shape.
    assert '"classification"' in content
    assert isinstance(summary, LiteLLMCallSummary)
    assert summary.status == "success"


def test_response_override_still_wins_for_call():
    fake = FakeLiteLLMClient(response_override='{"custom":true}')
    content, _ = fake.call("m", messages=[])
    assert content == '{"custom":true}'
