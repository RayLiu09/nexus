"""Tests for AI governance LLM retry behaviour (Review §1.1)."""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMCallSummary,
    LiteLLMErrorType,
)
from nexus_app.ai_governance.services import (
    _AI_CALL_MAX_RETRIES,
    _AI_CALL_RETRIABLE_ERRORS,
    AIGovernanceService,
)


def _ok_summary() -> LiteLLMCallSummary:
    return LiteLLMCallSummary(
        model_alias="m", request_id="r", latency_ms=10.0,
        status="success", input_hash="h",
    )


class _ScriptedClient:
    """LiteLLM client stub that returns a queued sequence of outcomes."""

    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def call(self, *args, **kwargs):
        self.calls += 1
        nxt = self.outcomes.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt, _ok_summary()


class TestRetriableErrors:
    def test_succeeds_after_one_transient_failure(self):
        client = _ScriptedClient([
            LiteLLMCallError("timeout", error_type=LiteLLMErrorType.TIMEOUT),
            "ok-output",
        ])
        with patch("time.sleep"):
            raw, summary, attempts = AIGovernanceService._call_llm_with_retry(
                client, "alias", [{"role": "user", "content": "x"}],
                temperature=0.2, max_tokens=128,
            )
        assert raw == "ok-output"
        assert attempts == 2
        assert client.calls == 2

    def test_exhausts_retries_then_raises(self):
        client = _ScriptedClient([
            LiteLLMCallError("ratelimit", error_type=LiteLLMErrorType.RATE_LIMIT)
            for _ in range(_AI_CALL_MAX_RETRIES + 1)
        ])
        with patch("time.sleep"):
            with pytest.raises(LiteLLMCallError) as exc_info:
                AIGovernanceService._call_llm_with_retry(
                    client, "alias", [{"role": "user", "content": "x"}],
                    temperature=0.2, max_tokens=128,
                )
        assert exc_info.value.error_type == LiteLLMErrorType.RATE_LIMIT
        assert client.calls == _AI_CALL_MAX_RETRIES + 1

    def test_all_retriable_types_get_retried(self):
        for et in _AI_CALL_RETRIABLE_ERRORS:
            client = _ScriptedClient([
                LiteLLMCallError("e1", error_type=et),
                "ok",
            ])
            with patch("time.sleep"):
                raw, _, attempts = AIGovernanceService._call_llm_with_retry(
                    client, "alias", [{"role": "user", "content": "x"}],
                    temperature=0.2, max_tokens=128,
                )
            assert raw == "ok", f"failed for error_type {et}"
            assert attempts == 2


class TestNonRetriableErrors:
    def test_invalid_request_aborts_immediately(self):
        client = _ScriptedClient([
            LiteLLMCallError("bad", error_type=LiteLLMErrorType.INVALID_REQUEST),
            "should-not-reach",
        ])
        with patch("time.sleep") as sleep_mock:
            with pytest.raises(LiteLLMCallError) as exc_info:
                AIGovernanceService._call_llm_with_retry(
                    client, "alias", [{"role": "user", "content": "x"}],
                    temperature=0.2, max_tokens=128,
                )
        assert exc_info.value.error_type == LiteLLMErrorType.INVALID_REQUEST
        assert client.calls == 1
        sleep_mock.assert_not_called()

    def test_unknown_error_type_aborts_immediately(self):
        # error_type=UNKNOWN is not in retriable set
        client = _ScriptedClient([
            LiteLLMCallError("???", error_type=LiteLLMErrorType.UNKNOWN),
        ])
        with patch("time.sleep"):
            with pytest.raises(LiteLLMCallError):
                AIGovernanceService._call_llm_with_retry(
                    client, "alias", [{"role": "user", "content": "x"}],
                    temperature=0.2, max_tokens=128,
                )
        assert client.calls == 1


class TestBackoffPattern:
    def test_backoff_grows(self):
        client = _ScriptedClient([
            LiteLLMCallError("e", error_type=LiteLLMErrorType.SERVER_ERROR)
            for _ in range(_AI_CALL_MAX_RETRIES + 1)
        ])
        with patch("time.sleep") as sleep_mock:
            with pytest.raises(LiteLLMCallError):
                AIGovernanceService._call_llm_with_retry(
                    client, "alias", [{"role": "user", "content": "x"}],
                    temperature=0.2, max_tokens=128,
                )
        # Each sleep call corresponds to a backoff between attempts; first
        # delay must be <= subsequent ones (monotonic non-decreasing).
        delays = [c.args[0] for c in sleep_mock.call_args_list]
        assert len(delays) == _AI_CALL_MAX_RETRIES
        assert delays == sorted(delays)
