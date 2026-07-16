"""A3 (§10 阶段 A + §1.15 §4.2.1) — Query Router v2 tool registry loader.

Parses `config/query_router_tools.json` (schema documented in that
file's `$comment`) into typed models the dispatcher can consume. Two
consumers:

* **B4 dispatcher** — `for_scenario("scenario_2")` returns the tool
  list to feed into `LiteLLMClientProtocol.call_with_tools`.
* **Layer 1 parameter extractor** — `union_of_required(scenario)`
  returns the merged parameter schema so the extractor can ask the
  LLM for every field any tool in the scenario might want.

Loader is deliberately strict about the JSON schema shape so config
drift surfaces at process start, not during a phase-B live request.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Public constants (§1.15 §4.2.1 remapped scenario ids)
# ---------------------------------------------------------------------------

ScenarioId = Literal[
    "scenario_1", "scenario_2", "scenario_3", "scenario_4", "scenario_5",
]
_SCENARIO_IDS: tuple[ScenarioId, ...] = (
    "scenario_1", "scenario_2", "scenario_3",
    "scenario_4", "scenario_5",
)

_DEFAULT_REGISTRY_PATH = (
    Path(__file__).parents[3] / "config" / "query_router_tools.json"
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ToolSpec(BaseModel):
    """One entry inside `scenarios.*.tools[]` — mirrors OpenAI's function
    calling schema so we can hand `.to_function_schema()` straight to
    `LiteLLMClientProtocol.call_with_tools(tools=[...])`."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    parameters: dict[str, Any]

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not value.startswith("internal."):
            raise ValueError(
                f"tool name must start with 'internal.' (got {value!r})"
            )
        return value

    @field_validator("parameters")
    @classmethod
    def _valid_parameters(cls, params: dict[str, Any]) -> dict[str, Any]:
        # Bare-minimum JSON Schema check — every tool's params must be
        # an object schema. We don't run a full JSON Schema validator
        # (would drag in a dependency for a check that pays off on
        # inspection alone), but we do guard the shape the dispatcher
        # assumes when threading arguments through Pydantic downstream.
        if params.get("type") != "object":
            raise ValueError(
                "tool parameters must be a JSON Schema object "
                "(missing or non-'object' `type`)"
            )
        properties = params.get("properties", {})
        if not isinstance(properties, dict):
            raise ValueError("tool parameters.properties must be a dict")
        required = params.get("required", [])
        if not isinstance(required, list):
            raise ValueError("tool parameters.required must be a list")
        for name in required:
            if name not in properties:
                raise ValueError(
                    f"required field {name!r} missing from properties "
                    f"(known: {sorted(properties.keys())})"
                )
        return params

    def to_function_schema(self) -> dict[str, Any]:
        """OpenAI-compatible `tools` entry for LiteLLM `call_with_tools`."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ScenarioSpec(BaseModel):
    """One scenario slice: business label + its allowed tools.

    `tools` may be empty (see scenario_5 Agentic RAG — dispatcher
    routes to the template executor rather than to LLM tool choice).
    """

    model_config = ConfigDict(extra="allow")  # `$comment` allowed

    business_label: str = Field(...)
    tools: list[ToolSpec] = Field(default_factory=list)


class ToolRegistry(BaseModel):
    """Root model — one entry per scenario_1..5.

    The registry is intentionally frozen after load; downstream code
    reads by scenario id. Missing a scenario is a hard error so config
    drift is loud.
    """

    model_config = ConfigDict(extra="allow")  # `$schema_version`, `$comment`
    scenarios: dict[str, ScenarioSpec]

    @model_validator(mode="after")
    def _every_scenario_present(self) -> "ToolRegistry":
        missing = set(_SCENARIO_IDS) - set(self.scenarios.keys())
        extra = set(self.scenarios.keys()) - set(_SCENARIO_IDS)
        if missing or extra:
            raise ValueError(
                "tool registry must define exactly "
                f"{sorted(_SCENARIO_IDS)}; "
                f"missing={sorted(missing)} extra={sorted(extra)}"
            )
        return self

    # ------------------------------------------------------------------ #
    # Read-side API
    # ------------------------------------------------------------------ #

    def for_scenario(self, scenario_id: str) -> list[ToolSpec]:
        try:
            return list(self.scenarios[scenario_id].tools)
        except KeyError as exc:
            raise KeyError(
                f"unknown scenario_id {scenario_id!r}; "
                f"expected one of {sorted(_SCENARIO_IDS)}"
            ) from exc

    def function_schemas_for(self, scenario_id: str) -> list[dict[str, Any]]:
        """Ready-to-hand list for `call_with_tools(tools=...)`.

        Empty for scenario_5 by design — Agentic RAG doesn't use
        LLM tool choice.
        """
        return [
            tool.to_function_schema()
            for tool in self.for_scenario(scenario_id)
        ]

    def find_tool(self, scenario_id: str, name: str) -> ToolSpec | None:
        for tool in self.for_scenario(scenario_id):
            if tool.name == name:
                return tool
        return None

    def union_of_required(self, scenario_id: str) -> list[str]:
        """Set of parameter names any tool in the scenario marks required.

        Used by Layer 1 parameter extractor to know which fields to
        prompt the LLM to pull out of the query.
        """
        seen: set[str] = set()
        ordered: list[str] = []
        for tool in self.for_scenario(scenario_id):
            for name in tool.parameters.get("required", []):
                if name not in seen:
                    seen.add(name)
                    ordered.append(name)
        return ordered


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_tool_registry(path: str | Path | None = None) -> ToolRegistry:
    """Read + validate the tool registry JSON.

    Raises `ValueError` / `pydantic.ValidationError` on any schema
    violation; the caller (nexus_api startup) treats that as a hard
    boot failure so bad config never reaches request handling.
    """
    p = Path(path) if path else _DEFAULT_REGISTRY_PATH
    if not p.exists():
        raise FileNotFoundError(f"tool registry not found: {p}")
    with p.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    return ToolRegistry.model_validate(raw)


@lru_cache(maxsize=1)
def get_default_tool_registry() -> ToolRegistry:
    """Process-wide singleton — loaded once, reused per request."""
    return load_tool_registry()


__all__ = [
    "ScenarioId",
    "ScenarioSpec",
    "ToolRegistry",
    "ToolSpec",
    "get_default_tool_registry",
    "load_tool_registry",
]
