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
    """Returns deterministic fake responses for demo/test environments."""

    def __init__(self, response_override: str | None = None) -> None:
        self._response_override = response_override

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
