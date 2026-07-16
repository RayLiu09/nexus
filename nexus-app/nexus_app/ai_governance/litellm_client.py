"""LiteLLM client adapter — OpenAI-compatible API only."""
from __future__ import annotations

import hashlib
import logging
import time
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class LiteLLMErrorType(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    INVALID_REQUEST = "invalid_request"
    SERVER_ERROR = "server_error"
    UNKNOWN = "unknown"


class LiteLLMCallError(Exception):
    def __init__(self, message: str, error_type: LiteLLMErrorType = LiteLLMErrorType.UNKNOWN) -> None:
        super().__init__(message)
        self.error_type = error_type


class RetryConfig(BaseModel):
    max_retries: int = Field(default=2, ge=0)
    backoff_seconds: float = Field(default=1.0, ge=0)


class LiteLLMConfig(BaseModel):
    base_url: str
    api_key_ref: str = Field(description="Reference name for secret, not the actual key")
    timeout: float = Field(default=30.0, gt=0)
    retry_config: RetryConfig = Field(default_factory=RetryConfig)


class LiteLLMCallSummary(BaseModel):
    model_alias: str
    request_id: str | None
    latency_ms: float
    status: str
    input_hash: str
    error_message: str | None = None


# ---------------------------------------------------------------------------
# A0 (§10 阶段 A + §1.11 决策 #4) — function calling / tool use support.
# ---------------------------------------------------------------------------
#
# The Query Router v2 dispatcher (phase B B4) needs to hand a list of
# tool schemas to the LLM and receive structured tool_calls back. We
# extend both the Protocol and the OpenAI-compatible client to accept
# `tools` + `tool_choice`, returning the raw `tool_calls` alongside the
# usual content string.
#
# Fallback contract: when the LLM chooses NOT to invoke any tool (e.g.
# `finish_reason=stop`, empty tool_calls) OR when arguments fail
# Pydantic validation upstream, the dispatcher receives an empty
# `tool_calls` list. §1.11 决策 #4 mandates that the caller then
# routes to the `unknown` fallback path — this client library does
# not retry.


class ToolCall(BaseModel):
    """Structured record of a single LLM-requested tool invocation.

    `arguments` stays as the raw JSON string emitted by the model so
    the caller can validate it against the tool's Pydantic schema
    (§1.11 decision — schema violations trigger dispatcher fallback,
    not a client-side retry).
    """

    id: str
    name: str
    arguments: str


class ToolCallingResult(BaseModel):
    """Return shape for `call_with_tools`.

    `content` — free-form text the model may have produced alongside
    the tool_calls (usually empty when tool_choice="required").
    `tool_calls` — one entry per requested invocation, empty when the
    model chose not to invoke any tool.
    `finish_reason` — mirrors the OpenAI-compatible payload so the
    dispatcher can distinguish "stop" (model deliberately answered
    without a tool) from "tool_calls" (model requested tool use).
    `summary` — inherits the standard call-level metadata (latency,
    request_id, etc.) for audit sinks.
    """

    content: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    summary: LiteLLMCallSummary


class LiteLLMClientProtocol(Protocol):
    def call(
        self,
        model_alias: str,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        response_format: dict[str, Any] | None = None,
    ) -> tuple[str, LiteLLMCallSummary]: ...

    def call_with_tools(
        self,
        model_alias: str,
        messages: list[dict[str, str]],
        *,
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> ToolCallingResult: ...


class RealLiteLLMClient:
    """Calls LiteLLM via OpenAI-compatible API."""

    def __init__(self, config: LiteLLMConfig, api_key: str) -> None:
        try:
            from openai import APIStatusError, APITimeoutError, OpenAI, RateLimitError
            self._openai_exc = (APIStatusError, APITimeoutError, RateLimitError)
            self._APITimeoutError = APITimeoutError
            self._RateLimitError = RateLimitError
        except ImportError as exc:
            raise ImportError("openai package is required for RealLiteLLMClient") from exc

        self._config = config
        self._client = OpenAI(base_url=config.base_url, api_key=api_key,
                              timeout=config.timeout)

    def call(
        self,
        model_alias: str,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        response_format: dict[str, Any] | None = None,
    ) -> tuple[str, LiteLLMCallSummary]:
        input_hash = _hash_messages(messages)
        kwargs: dict[str, Any] = dict(
            model=model_alias,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if response_format:
            kwargs["response_format"] = response_format

        start = time.monotonic()
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            error_type = self._classify_error(exc)
            summary = LiteLLMCallSummary(
                model_alias=model_alias, request_id=None, latency_ms=latency_ms,
                status="failed", input_hash=input_hash, error_message=str(exc),
            )
            logger.warning("LiteLLM call failed alias=%s error_type=%s latency_ms=%.1f",
                           model_alias, error_type, latency_ms)
            raise LiteLLMCallError(f"LiteLLM call failed: {exc}", error_type) from exc

        latency_ms = (time.monotonic() - start) * 1000
        content = resp.choices[0].message.content or ""
        request_id = getattr(resp, "id", None)
        summary = LiteLLMCallSummary(
            model_alias=model_alias, request_id=request_id, latency_ms=latency_ms,
            status="success", input_hash=input_hash,
        )
        logger.info("LiteLLM call ok alias=%s request_id=%s latency_ms=%.1f",
                    model_alias, request_id, latency_ms)
        return content, summary

    def call_with_tools(
        self,
        model_alias: str,
        messages: list[dict[str, str]],
        *,
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> ToolCallingResult:
        """A0 (§1.11 决策 #4) — pass tools through to OpenAI-compatible chat.

        Returns `tool_calls=[]` when the model chose not to invoke any
        tool. The caller (B4 dispatcher) is expected to fall back to the
        `unknown` scenario in that case — this method never retries.
        Errors surface as `LiteLLMCallError` exactly like `call()`.
        """
        input_hash = _hash_messages(messages)
        kwargs: dict[str, Any] = dict(
            model=model_alias,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
        )
        start = time.monotonic()
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            error_type = self._classify_error(exc)
            logger.warning(
                "LiteLLM call_with_tools failed alias=%s error_type=%s "
                "latency_ms=%.1f",
                model_alias, error_type, latency_ms,
            )
            raise LiteLLMCallError(
                f"LiteLLM call_with_tools failed: {exc}", error_type,
            ) from exc

        latency_ms = (time.monotonic() - start) * 1000
        choice = resp.choices[0]
        message = choice.message
        content = message.content or ""
        raw_tool_calls = getattr(message, "tool_calls", None) or []
        parsed_tool_calls: list[ToolCall] = []
        for tc in raw_tool_calls:
            # OpenAI SDK returns objects with `.function.name/arguments`
            # nested; keep the parsing defensive so a shape change
            # doesn't crash retrieval.
            fn = getattr(tc, "function", None)
            if fn is None:
                continue
            parsed_tool_calls.append(ToolCall(
                id=getattr(tc, "id", ""),
                name=getattr(fn, "name", ""),
                arguments=getattr(fn, "arguments", "") or "",
            ))
        finish_reason = getattr(choice, "finish_reason", None)
        request_id = getattr(resp, "id", None)
        summary = LiteLLMCallSummary(
            model_alias=model_alias, request_id=request_id, latency_ms=latency_ms,
            status="success", input_hash=input_hash,
        )
        logger.info(
            "LiteLLM call_with_tools ok alias=%s request_id=%s "
            "latency_ms=%.1f tool_calls=%d finish=%s",
            model_alias, request_id, latency_ms,
            len(parsed_tool_calls), finish_reason,
        )
        return ToolCallingResult(
            content=content,
            tool_calls=parsed_tool_calls,
            finish_reason=finish_reason,
            summary=summary,
        )

    def _classify_error(self, exc: Exception) -> LiteLLMErrorType:
        name = type(exc).__name__
        if "Timeout" in name:
            return LiteLLMErrorType.TIMEOUT
        if "RateLimit" in name:
            return LiteLLMErrorType.RATE_LIMIT
        if "InvalidRequest" in name or "BadRequest" in name:
            return LiteLLMErrorType.INVALID_REQUEST
        if "APIStatus" in name or "Server" in name:
            return LiteLLMErrorType.SERVER_ERROR
        return LiteLLMErrorType.UNKNOWN


class FakeLiteLLMClient:
    """Returns deterministic fake responses for demo/test environments.

    Two response overrides — one for `call()` (JSON content string) and
    one for `call_with_tools()` (list of ToolCall). Both default to
    canned demo payloads so tests that don't care about the actual
    LLM response can just instantiate `FakeLiteLLMClient()`.
    """

    def __init__(
        self,
        response_override: str | None = None,
        *,
        tool_calls_override: list[ToolCall] | None = None,
        content_override_with_tools: str = "",
        finish_reason_with_tools: str | None = None,
    ) -> None:
        self._response_override = response_override
        # Empty list → simulate "model chose not to invoke any tool" so
        # dispatcher tests can exercise the §1.11 decision #4 fallback
        # without a custom subclass. `None` (the default) keeps the
        # historical single-tool canned response for backwards compat.
        self._tool_calls_override = tool_calls_override
        self._content_override_with_tools = content_override_with_tools
        self._finish_reason_with_tools = finish_reason_with_tools

    def call(
        self,
        model_alias: str,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        response_format: dict[str, Any] | None = None,
    ) -> tuple[str, LiteLLMCallSummary]:
        import json as _json
        input_hash = _hash_messages(messages)
        content = self._response_override or _json.dumps({
            "classification": "D4",
            "level": "L2",
            "tags": ["knowledge_asset", "training_material"],
            "org_scope": "all",
            "quality_scores": {
                "completeness": 85.0,
                "accuracy": 80.0,
                "consistency": 90.0,
                "usability": 75.0
            },
            "overall_score": 83.0,
            "evidence_refs": [
                {"field": "title", "value": "sample title", "confidence": 0.9, "source_position": None}
            ],
            "confidence": 0.88,
            "reasoning": "Fake response for demo/test"
        })
        summary = LiteLLMCallSummary(
            model_alias=model_alias, request_id="fake-req-001",
            latency_ms=50.0, status="success", input_hash=input_hash,
        )
        return content, summary

    def call_with_tools(
        self,
        model_alias: str,
        messages: list[dict[str, str]],
        *,
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> ToolCallingResult:
        input_hash = _hash_messages(messages)
        if self._tool_calls_override is not None:
            tool_calls = list(self._tool_calls_override)
        else:
            # Canned "invoke the first available tool with empty args"
            # response — enough for smoke tests that don't want to
            # micro-manage the LLM's decision.
            tool_calls = []
            if tools:
                first = tools[0]
                fn = first.get("function", first)
                tool_calls.append(ToolCall(
                    id="fake-tool-call-1",
                    name=fn.get("name", "unknown"),
                    arguments="{}",
                ))
        finish_reason = self._finish_reason_with_tools or (
            "tool_calls" if tool_calls else "stop"
        )
        return ToolCallingResult(
            content=self._content_override_with_tools,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            summary=LiteLLMCallSummary(
                model_alias=model_alias, request_id="fake-req-tools-001",
                latency_ms=25.0, status="success", input_hash=input_hash,
            ),
        )


class CassetteLiteLLMClient:
    """Replay pre-recorded responses.

    Two dispatch modes:

    * **Sequential** — pass ``responses: list[str]``.  Each ``.call()``
      consumes the next entry.  This is the M-C.2 mode used by the
      golden retrieval harness (intent → planner order).
    * **Keyed** — pass ``responses_by_alias: dict[str, list[str]]``.
      Each ``.call()`` looks up the next unconsumed entry for the given
      ``model_alias``.  Matches happen by:

      1. exact alias equality;
      2. substring match against a key (``"body-markdown" in "body-markdown-v1"``);
      3. fallback ``"_default"`` key if present.

      This is the M-D mode that lets Pipeline B ingest tests (or any
      multi-stage LLM flow) replay per-stage LiteLLM traffic without
      requiring the caller to know the exact call order.

    Running out of tape (or missing a matching key) raises so silent
    under-recording surfaces as a hard failure rather than mystery
    LLM behaviour.  Responses are the raw ``choices[0].message.content``
    string the real client would produce — JSON when the caller passes
    ``response_format={"type": "json_object"}``, else free text.
    """

    def __init__(
        self,
        responses: list[str] | None = None,
        *,
        responses_by_alias: dict[str, list[str]] | None = None,
    ) -> None:
        if responses is None and responses_by_alias is None:
            raise ValueError(
                "CassetteLiteLLMClient requires responses or responses_by_alias"
            )
        if responses is not None and responses_by_alias is not None:
            raise ValueError(
                "CassetteLiteLLMClient accepts responses OR responses_by_alias, not both"
            )
        if responses is not None:
            if not responses:
                raise ValueError(
                    "CassetteLiteLLMClient requires at least one response"
                )
            self._mode: str = "sequential"
            self._responses: list[str] = list(responses)
            self._index: int = 0
            self._keyed: dict[str, list[str]] = {}
            self._keyed_index: dict[str, int] = {}
        else:
            assert responses_by_alias is not None
            if not responses_by_alias or not any(responses_by_alias.values()):
                raise ValueError(
                    "responses_by_alias must have at least one non-empty entry"
                )
            self._mode = "keyed"
            self._responses = []
            self._index = 0
            self._keyed = {k: list(v) for k, v in responses_by_alias.items()}
            self._keyed_index = {k: 0 for k in self._keyed}
        self.calls: list[dict[str, Any]] = []

    def _resolve_keyed(self, model_alias: str) -> str:
        """Return the next unconsumed response for ``model_alias``.

        Look-up order: exact key → substring key → ``"_default"`` fallback.
        Raises RuntimeError on no match or exhausted tape.
        """
        # 1) exact match
        if model_alias in self._keyed:
            idx = self._keyed_index[model_alias]
            if idx < len(self._keyed[model_alias]):
                self._keyed_index[model_alias] = idx + 1
                return self._keyed[model_alias][idx]

        # 2) substring — key contained in alias (e.g. key "governance" matches
        # alias "governance-multi-v2").  Prefer the longest matching key to
        # avoid ambiguity when both "governance" and "governance-multi" are
        # recorded.
        candidates = sorted(
            (k for k in self._keyed if k in model_alias),
            key=len,
            reverse=True,
        )
        for key in candidates:
            idx = self._keyed_index[key]
            if idx < len(self._keyed[key]):
                self._keyed_index[key] = idx + 1
                return self._keyed[key][idx]

        # 3) explicit default bucket
        if "_default" in self._keyed:
            idx = self._keyed_index["_default"]
            if idx < len(self._keyed["_default"]):
                self._keyed_index["_default"] = idx + 1
                return self._keyed["_default"][idx]

        exhausted = {
            k: (self._keyed_index[k], len(v))
            for k, v in self._keyed.items()
        }
        raise RuntimeError(
            f"CassetteLiteLLMClient (keyed) has no unconsumed response for "
            f"model_alias={model_alias!r}; per-key state (consumed/total)="
            f"{exhausted}"
        )

    def call(
        self,
        model_alias: str,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        response_format: dict[str, Any] | None = None,
    ) -> tuple[str, LiteLLMCallSummary]:
        if self._mode == "sequential":
            if self._index >= len(self._responses):
                raise RuntimeError(
                    f"CassetteLiteLLMClient exhausted after {self._index} call(s); "
                    f"caller made an extra .call() with model_alias={model_alias!r}"
                )
            content = self._responses[self._index]
            self._index += 1
        else:
            content = self._resolve_keyed(model_alias)

        input_hash = _hash_messages(messages)
        self.calls.append({
            "model_alias": model_alias,
            "input_hash": input_hash,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": response_format,
        })
        summary = LiteLLMCallSummary(
            model_alias=model_alias,
            request_id=f"cassette-{len(self.calls)}",
            latency_ms=0.0,
            status="success",
            input_hash=input_hash,
        )
        return content, summary


def create_litellm_client(
    config: LiteLLMConfig | None = None,
    api_key: str = "",
    *,
    fake: bool = False,
) -> LiteLLMClientProtocol:
    if fake:
        return FakeLiteLLMClient()
    if config is None:
        raise ValueError("config is required when fake=False")
    return RealLiteLLMClient(config, api_key)


def _hash_messages(messages: list[dict[str, str]]) -> str:
    import json as _json
    payload = _json.dumps(messages, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
