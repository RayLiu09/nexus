"""B3 (§10 阶段 B) — Layer-1 parameter extractor for query-router-v2.

Given a user query + a classified `intent`, extract the values the
downstream tools need. The parameter schema is computed on demand as
the **union of every tool's `parameters` under the intent** (§1.15
scenario_1..5 groupings), so:

* If two tools in the same scenario both take `major_name`, the
  extractor prompts the LLM once for `major_name`.
* If one tool requires `major_code` and another treats it as optional,
  the union keeps it optional; the caller (Layer 2 dispatcher) will
  drop the field for tools that don't accept it.

The LLM output shape is fixed:

```json
{
  "extracted_params": {"major_name": "跨境电商", "top_k": 5, ...},
  "missing_required": ["major_code"]
}
```

Failure paths follow the same pattern as `intent_v2`:

* LLM error / malformed JSON / schema drift → return an empty extract
  with `fallback_reason` populated so the dispatcher can decide
  whether to prompt the user or fall through to `unknown`.
* Empty query / unknown intent → short-circuit before hitting the LLM.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMClientProtocol,
)
from nexus_app.retrieval.prompt_profiles_v2 import (
    PARAM_EXTRACT_V2_PROFILE_NAME,
    get_active_v2_prompt,
)
from nexus_app.retrieval.tools_registry import (
    ToolRegistry,
    ToolSpec,
    get_default_tool_registry,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Contract types
# ---------------------------------------------------------------------------


class ExtractedParamsLLMOutput(BaseModel):
    """LLM output shape.

    `extra="ignore"` — the model sometimes tacks on reasoning text; we
    keep the strict fields and drop the rest.
    """

    model_config = ConfigDict(extra="ignore")

    extracted_params: dict[str, Any] = Field(default_factory=dict)
    missing_required: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class ParamExtractionResult:
    """What the dispatcher receives.

    `extracted_params` — keys are parameter names from the scenario's
    union schema; values are whatever the LLM produced (already
    validated against JSON schema types). Missing / null values are
    excluded so downstream code can just `.get()` without None checks.

    `missing_required` — parameter names the LLM saw as required (in
    the union schema) but couldn't extract. Empty when everything
    required was found.

    `parameters_schema` — the union JSON schema the LLM was asked to
    fill. Callers audit this for observability.

    `fallback_reason` — set when we returned an empty result for a
    reason other than the LLM saying "nothing to extract".
    """

    extracted_params: dict[str, Any]
    missing_required: list[str]
    parameters_schema: dict[str, Any]
    fallback_reason: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Union-schema builder
# ---------------------------------------------------------------------------


def build_union_schema(tools: list[ToolSpec]) -> dict[str, Any]:
    """Combine every tool's `parameters` into a single JSON schema.

    * `properties` — union of every tool's properties. When two tools
      declare the same field with different types, the FIRST tool wins
      (arbitrary but stable — tools are ordered per the registry file).
    * `required` — a field is required in the union iff every tool in
      the scenario declares it and marks it required. In mixed-tool
      scenarios, fields required by only one optional branch (for
      example scenario_2's `job_title` role-graph field) must not
      become scenario-level required.

    The result is what the extractor asks the LLM to fill.
    """
    properties: dict[str, Any] = {}
    required_counts: dict[str, int] = {}
    declared_counts: dict[str, int] = {}

    for tool in tools:
        params = tool.parameters
        for name, definition in params.get("properties", {}).items():
            declared_counts[name] = declared_counts.get(name, 0) + 1
            properties.setdefault(name, definition)
        for name in params.get("required", []):
            required_counts[name] = required_counts.get(name, 0) + 1

    tool_count = len(tools)
    required_union: list[str] = sorted(
        name for name, count in required_counts.items()
        if declared_counts.get(name, 0) == tool_count and count == tool_count
    )

    return {
        "type": "object",
        "properties": properties,
        "required": required_union,
    }


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


@dataclass
class ParameterExtractorV2:
    """Layer-1 parameter extractor.

    Constructor accepts a `LiteLLMClientProtocol` and an optional
    `ToolRegistry` — tests inject a fake for both. Production callers
    typically pass `get_default_tool_registry()`.
    """

    llm_client: LiteLLMClientProtocol
    registry: ToolRegistry | None = None

    def extract(
        self, session: Session, *, query: str, intent: str,
    ) -> ParamExtractionResult:
        query = (query or "").strip()
        if not query:
            return ParamExtractionResult(
                extracted_params={},
                missing_required=[],
                parameters_schema={},
                fallback_reason="empty_query",
            )

        # `unknown` intents don't have a tool set — the dispatcher
        # short-circuits to the fallback path, so extraction is moot.
        if intent == "unknown":
            return ParamExtractionResult(
                extracted_params={},
                missing_required=[],
                parameters_schema={},
                fallback_reason="unknown_intent",
            )

        registry = self.registry or get_default_tool_registry()
        try:
            tools = registry.for_scenario(intent)
        except KeyError:
            return ParamExtractionResult(
                extracted_params={},
                missing_required=[],
                parameters_schema={},
                fallback_reason="unknown_intent",
            )
        if not tools:
            # scenario_5 (Agentic RAG) legitimately has zero tools;
            # dispatcher runs the template instead.
            return ParamExtractionResult(
                extracted_params={},
                missing_required=[],
                parameters_schema={},
                fallback_reason="no_tools_for_intent",
            )

        params_schema = build_union_schema(tools)

        try:
            profile = get_active_v2_prompt(session, PARAM_EXTRACT_V2_PROFILE_NAME)
        except LookupError as exc:
            logger.warning("param_extract_v2: prompt profile missing — %s", exc)
            return ParamExtractionResult(
                extracted_params={},
                missing_required=list(params_schema["required"]),
                parameters_schema=params_schema,
                fallback_reason="prompt_profile_missing",
            )

        messages = _build_messages(
            profile.prompt_template,
            query=query,
            intent=intent,
            params_schema=params_schema,
        )

        try:
            content, _summary = self.llm_client.call(
                profile.litellm_model_alias,
                messages,
                temperature=profile.temperature,
                max_tokens=1024,
                response_format={"type": "json_object"},
            )
        except LiteLLMCallError as exc:
            logger.warning(
                "param_extract_v2: LLM call failed error_type=%s",
                exc.error_type,
            )
            return ParamExtractionResult(
                extracted_params={},
                missing_required=list(params_schema["required"]),
                parameters_schema=params_schema,
                fallback_reason="llm_call_failed",
                warnings=(str(exc.error_type),),
            )

        try:
            parsed = self._parse(content)
        except ValueError as exc:
            logger.warning("param_extract_v2: output parse failed — %s", exc)
            return ParamExtractionResult(
                extracted_params={},
                missing_required=list(params_schema["required"]),
                parameters_schema=params_schema,
                fallback_reason="output_parse_failed",
            )

        # Post-process — drop null values so `.get(...)` in the
        # dispatcher doesn't need to null-check, and clip the
        # missing_required list to fields that are actually in the
        # union schema (a model may hallucinate a name).
        cleaned = {
            k: v for k, v in parsed.extracted_params.items()
            if v is not None and k in params_schema["properties"]
        }
        # A field appearing in the LLM's extracted_params is present —
        # remove it from missing_required even if the LLM listed it.
        declared_required = set(params_schema["required"])
        seen_names = set(cleaned.keys())
        model_missing = {
            name for name in parsed.missing_required
            if name in declared_required and name not in seen_names
        }
        # A required field the LLM forgot to mention as missing yet
        # also didn't extract — surface it. (Rare, but defends against
        # sloppy `missing_required=[]` output.)
        for name in declared_required:
            if name not in seen_names:
                model_missing.add(name)

        return ParamExtractionResult(
            extracted_params=cleaned,
            missing_required=sorted(model_missing),
            parameters_schema=params_schema,
        )

    # ------------------------------------------------------------------ #
    # Parsing
    # ------------------------------------------------------------------ #

    def _parse(self, content: str) -> ExtractedParamsLLMOutput:
        try:
            payload = json.loads(content)
        except (TypeError, ValueError) as exc:
            raise ValueError("param extraction output is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("param extraction output must be a JSON object")
        try:
            return ExtractedParamsLLMOutput.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(
                f"param extraction output does not match schema: {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# Message construction
# ---------------------------------------------------------------------------


def _build_messages(
    prompt_template: str,
    *,
    query: str,
    intent: str,
    params_schema: dict[str, Any],
) -> list[dict[str, str]]:
    """Fill the 3 template placeholders (`str.replace`, safe against `{}`)."""
    filled = (
        prompt_template
        .replace("{{QUERY}}", query)
        .replace("{{INTENT}}", intent)
        .replace(
            "{{PARAMS_SCHEMA}}",
            json.dumps(params_schema, ensure_ascii=False, indent=2),
        )
    )
    return [{"role": "user", "content": filled}]


__all__ = [
    "ExtractedParamsLLMOutput",
    "ParamExtractionResult",
    "ParameterExtractorV2",
    "build_union_schema",
]
