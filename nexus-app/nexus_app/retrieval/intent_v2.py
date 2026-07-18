"""B2 (§10 阶段 B) — Query Router v2 intent classifier.

Layer-1 intent classifier for the v2 orchestration flow. Takes a
user query and returns exactly one of the 5 §1.15 business-view
scenarios (or `unknown`) plus a confidence float.

Design notes:

* We keep the v1 `IntentRecognitionService` intact (see `intent.py`)
  because the legacy DAG orchestrator still uses its rich
  `RetrievalIntent` shape. v2 is a **thin, focused** replacement that
  the B4 dispatcher / B6-B7 main entry points import directly.

* The classifier reuses the `LiteLLMClientProtocol` and the shared
  `ai_prompt_profile` framework (see `prompt_profiles_v2.py`) so
  business owners can edit the prompt without a code deploy.

* When the LLM call fails or the JSON is malformed, we return
  `IntentV2Result` with `intent="unknown"` and `confidence=0.0` — the
  B4 dispatcher then routes to the §六 unknown-fallback path.

* When the LLM returns a real scenario id but confidence <
  `confidence_threshold`, we still return the raw intent + the
  `low_confidence=True` flag so the dispatcher can decide whether to
  downgrade (default: yes, downgrade to `unknown`).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMClientProtocol,
)
from nexus_app.retrieval.prompt_profiles_v2 import (
    INTENT_V2_PROFILE_NAME,
    get_active_v2_prompt,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Contract types
# ---------------------------------------------------------------------------

IntentId = Literal[
    "scenario_1",
    "scenario_2",
    "scenario_3",
    "scenario_4",
    "scenario_5",
    "unknown",
]

_SUPPORTED_INTENTS: frozenset[str] = frozenset({
    "scenario_1", "scenario_2", "scenario_3",
    "scenario_4", "scenario_5", "unknown",
})

DEFAULT_CONFIDENCE_THRESHOLD: float = 0.6


class IntentV2LLMOutput(BaseModel):
    """The JSON shape we ask the LLM to produce (prompt output schema).

    Extra fields the model might sneak in are stripped — we care only
    about `intent` + `confidence`.
    """

    model_config = ConfigDict(extra="ignore")

    intent: IntentId
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("intent", mode="before")
    @classmethod
    def _lowercase_and_validate(cls, value: object) -> str:
        """Accept minor casing / whitespace drift from the LLM.

        Anything unrecognised is coerced to `unknown` so a rogue label
        never crashes the dispatcher — the caller falls through to the
        unknown-scenario path per §六.
        """
        if not isinstance(value, str):
            return "unknown"
        canonical = value.strip().lower()
        if canonical not in _SUPPORTED_INTENTS:
            return "unknown"
        return canonical


@dataclass(frozen=True)
class IntentV2Result:
    """What the dispatcher gets back.

    `low_confidence` — True when the classifier returned a real scenario
    id but its confidence < `confidence_threshold`. Callers may choose
    to downgrade to unknown OR let the classification stand.
    `fallback_reason` — populated when we returned `unknown` for a
    reason other than the LLM saying so (e.g. malformed output, LLM
    error). Nil when the model itself picked `unknown`.
    """

    intent: str
    confidence: float
    low_confidence: bool = False
    fallback_reason: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


@dataclass
class IntentClassifierV2:
    """Layer-1 intent classifier for query-router-v2.

    Constructor takes a `LiteLLMClientProtocol` so tests can drop in a
    `FakeLiteLLMClient` without hitting the network. The active prompt
    template is fetched from `ai_prompt_profile` on each `.classify()`
    call so an admin edit through the console applies to the next
    request (no restart needed).
    """

    llm_client: LiteLLMClientProtocol
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD

    def classify(self, session: Session, query: str) -> IntentV2Result:
        """Classify the query.

        Returns:
            IntentV2Result with the intent id and confidence; on any
            recoverable failure the result carries
            `intent="unknown"` and a populated `fallback_reason`.
        """
        query = (query or "").strip()
        if not query:
            return IntentV2Result(
                intent="unknown",
                confidence=0.0,
                fallback_reason="empty_query",
            )

        try:
            profile = get_active_v2_prompt(session, INTENT_V2_PROFILE_NAME)
        except LookupError as exc:
            logger.warning("intent_v2: prompt profile missing — %s", exc)
            return IntentV2Result(
                intent="unknown",
                confidence=0.0,
                fallback_reason="prompt_profile_missing",
            )

        messages = _build_messages(profile.prompt_template, query)
        try:
            content, _summary = self.llm_client.call(
                profile.litellm_model_alias,
                messages,
                temperature=profile.temperature,
                max_tokens=256,
                response_format={"type": "json_object"},
            )
        except LiteLLMCallError as exc:
            logger.warning(
                "intent_v2: LLM call failed error_type=%s", exc.error_type,
            )
            return IntentV2Result(
                intent="unknown",
                confidence=0.0,
                fallback_reason="llm_call_failed",
                warnings=(str(exc.error_type),),
            )

        try:
            parsed = self._parse(content)
        except ValueError as exc:
            logger.warning("intent_v2: output parse failed — %s", exc)
            return IntentV2Result(
                intent="unknown",
                confidence=0.0,
                fallback_reason="output_parse_failed",
            )

        # `unknown` from the model itself is a first-class answer,
        # not a fallback — leave `fallback_reason=None`.
        if parsed.intent == "unknown":
            return IntentV2Result(
                intent="unknown",
                confidence=parsed.confidence,
            )

        low_conf = parsed.confidence < self.confidence_threshold
        return IntentV2Result(
            intent=parsed.intent,
            confidence=parsed.confidence,
            low_confidence=low_conf,
        )

    # ------------------------------------------------------------------ #
    # Parsing
    # ------------------------------------------------------------------ #

    def _parse(self, content: str) -> IntentV2LLMOutput:
        try:
            payload = json.loads(content)
        except (TypeError, ValueError) as exc:
            raise ValueError("intent output is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("intent output must be a JSON object")
        try:
            return IntentV2LLMOutput.model_validate(payload)
        except Exception as exc:  # noqa: BLE001 - Pydantic ValidationError, kept broad for message
            raise ValueError(f"intent output schema mismatch: {exc}") from exc


# ---------------------------------------------------------------------------
# Message construction
# ---------------------------------------------------------------------------


def _build_messages(prompt_template: str, query: str) -> list[dict[str, str]]:
    """Fill the `{{QUERY}}` placeholder and package the OpenAI messages.

    Placeholder replacement uses `str.replace` (not `str.format` or
    Jinja) so any accidental curly-brace content in the query text
    (e.g. code snippets from users pasting SQL) doesn't crash the
    prompt build.
    """
    filled = prompt_template.replace("{{QUERY}}", query)
    return [{"role": "user", "content": filled}]


__all__ = [
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "IntentClassifierV2",
    "IntentId",
    "IntentV2LLMOutput",
    "IntentV2Result",
]
