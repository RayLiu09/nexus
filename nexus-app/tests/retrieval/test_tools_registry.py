"""A3 (§10 阶段 A + §1.15 §4.2.1) — tool registry loader.

Verifies:
* Loader parses the shipped `config/query_router_tools.json` cleanly
  and every scenario_1..5 is present with the expected business shape.
* Cross-scenario checks: same tool name (`internal.query_capability_graph_by_major`)
  legitimately appears in scenario_2 (`ability_analysis` const) and
  scenario_3 (`teaching_standard` const) — proves the § 1.15 dispatch
  scheme is honoured.
* Business rules: every tool name starts with `internal.`; required
  params are declared in properties; scenario_5 has zero tools
  (Agentic RAG placeholder).
* A0/A3 联调 (§1.11 闭合项): the JSON schemas built by the registry
  round-trip through `LiteLLMClientProtocol.call_with_tools` — every
  scenario_1..4 tool can be handed to A0 without schema shape errors.
* Cross-asset原则合规性 (§2.5.0): every tool's required parameters
  are business dimensions, not trace fields.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from nexus_app.ai_governance.litellm_client import FakeLiteLLMClient, ToolCall
from nexus_app.retrieval.tools_registry import (
    ToolRegistry,
    ToolSpec,
    get_default_tool_registry,
    load_tool_registry,
)


# Fields that are trace-only (§2.5.0 跨资产原则 — never required as
# primary business dimensions). Reused by the compliance check below.
_TRACE_FIELDS: frozenset[str] = frozenset({
    "normalized_ref_id",
    "dataset_id",
    "build_id",
})


# ---------------------------------------------------------------------------
# Positive parse — default config file
# ---------------------------------------------------------------------------


class TestDefaultRegistry:
    def test_registry_loads_and_lists_five_scenarios(self):
        reg = load_tool_registry()
        assert set(reg.scenarios) == {
            "scenario_1", "scenario_2", "scenario_3",
            "scenario_4", "scenario_5",
        }

    def test_scenario_business_labels_match_v2_0_1_semantics(self):
        reg = load_tool_registry()
        # Sanity-check the labels match §1.15 remapping — a maintainer
        # accidentally renaming the label back to the v2.0 "综合性检索"
        # would signal doc drift.
        assert "讯息类" in reg.scenarios["scenario_1"].business_label
        assert "结构化数据" in reg.scenarios["scenario_2"].business_label
        assert "专业信息" in reg.scenarios["scenario_3"].business_label
        assert "教材类" in reg.scenarios["scenario_4"].business_label
        assert "Agentic RAG" in reg.scenarios["scenario_5"].business_label

    def test_scenario_5_carries_zero_tools(self):
        """Agentic RAG (scenario_5) is dispatched via the template
        executor, not via LLM tool choice — the registry entry exists
        but its tool list is empty (§1.15 §4.2.1)."""
        reg = load_tool_registry()
        assert reg.scenarios["scenario_5"].tools == []
        assert reg.for_scenario("scenario_5") == []
        assert reg.function_schemas_for("scenario_5") == []

    def test_get_default_tool_registry_is_singleton(self):
        # Cached — same object across calls, so callers can compare
        # references without worrying about repeated JSON parses.
        assert get_default_tool_registry() is get_default_tool_registry()

    def test_every_tool_name_prefixed_with_internal(self):
        reg = load_tool_registry()
        for scenario_id in reg.scenarios:
            for tool in reg.for_scenario(scenario_id):
                assert tool.name.startswith("internal."), (
                    f"tool {tool.name!r} in {scenario_id} violates namespace rule"
                )


# ---------------------------------------------------------------------------
# Cross-scenario overlap — query_capability_graph_by_major appears twice
# ---------------------------------------------------------------------------


class TestScenarioOverlap:
    def test_capability_graph_tool_registered_in_both_scenario_2_and_3(self):
        """§1.15 §4.2.1 — same tool name, two different `const` values
        for `build_type`. Both entries must be reachable so B4
        dispatcher picks the correct schema per scenario."""
        reg = load_tool_registry()
        tool_2 = reg.find_tool("scenario_2", "internal.query_capability_graph_by_major")
        tool_3 = reg.find_tool("scenario_3", "internal.query_capability_graph_by_major")
        assert tool_2 is not None
        assert tool_3 is not None
        assert (
            tool_2.parameters["properties"]["build_type"]["const"]
            == "ability_analysis"
        )
        assert (
            tool_3.parameters["properties"]["build_type"]["const"]
            == "teaching_standard"
        )

    def test_major_information_tool_replaces_teaching_standard_outline_search(self):
        reg = load_tool_registry()
        # scenario_1 → industry_research_kb (const)
        s1_tool = reg.find_tool("scenario_1", "internal.search_chunks_by_semantic")
        assert (
            s1_tool.parameters["properties"]["kb"]["const"]
            == "industry_research_kb"
        )
        s3_tool = reg.find_tool("scenario_3", "internal.query_major_information")
        assert s3_tool is not None
        assert "outline_node" not in s3_tool.parameters["properties"]
        assert "units" in s3_tool.parameters["required"]
        assert "occupation_oriented" in s3_tool.parameters["properties"]["units"]["items"]["enum"]
        # scenario_4 → deterministic semantic retrieval only; outline /
        # evidence graph APIs remain implemented but are not model-selectable.
        s4_tools = reg.for_scenario("scenario_4")
        assert [tool.name for tool in s4_tools] == [
            "internal.search_chunks_by_semantic",
        ]
        s4_tool = reg.find_tool("scenario_4", "internal.search_chunks_by_semantic")
        assert set(s4_tool.parameters["properties"]["kb"]["enum"]) == {
            "course_textbook", "practical_training_kb",
        }
        assert reg.find_tool("scenario_4", "internal.get_outline_subtree") is None
        assert reg.find_tool("scenario_4", "internal.get_evidence_graph_by_ref") is None


# ---------------------------------------------------------------------------
# Cross-asset compliance check (§2.5.0)
# ---------------------------------------------------------------------------


class TestCrossAssetPrinciple:
    def test_no_trace_field_marked_required_in_tool_params(self):
        """§2.5.0 tenet — trace fields (normalized_ref_id / dataset_id /
        build_id) are output helpers, never primary business
        dimensions. get_evidence_graph_by_ref is the deliberate
        exception (a "trace-first" fetcher, not a search)."""
        reg = load_tool_registry()
        # The one tool that legitimately requires a trace field as
        # its sole input — a straight lookup, not a business search.
        exceptions = {"internal.get_evidence_graph_by_ref",
                      "internal.get_job_demand_role_graph"}
        for scenario_id in reg.scenarios:
            for tool in reg.for_scenario(scenario_id):
                if tool.name in exceptions:
                    continue
                required = set(tool.parameters.get("required", []))
                offenders = required & _TRACE_FIELDS
                assert not offenders, (
                    f"{tool.name} in {scenario_id} marks trace fields "
                    f"{offenders} as required — violates §2.5.0"
                )


# ---------------------------------------------------------------------------
# Read-side helpers
# ---------------------------------------------------------------------------


class TestReadSideHelpers:
    def test_union_of_required_deduplicates(self):
        reg = load_tool_registry()
        # scenario_2 has 5 tools with overlapping required sets
        # (`major` / `dataset_id` / `build_type`). Order is preserved
        # per §A3 DoD.
        required = reg.union_of_required("scenario_2")
        assert len(required) == len(set(required))  # deduped

    def test_function_schemas_shape(self):
        reg = load_tool_registry()
        schemas = reg.function_schemas_for("scenario_1")
        assert schemas == [{
            "type": "function",
            "function": {
                "name": schemas[0]["function"]["name"],  # unchecked here
                "description": schemas[0]["function"]["description"],
                "parameters": schemas[0]["function"]["parameters"],
            },
        }]
        assert schemas[0]["function"]["name"] == "internal.search_chunks_by_semantic"

    def test_for_scenario_unknown_id_raises(self):
        reg = load_tool_registry()
        with pytest.raises(KeyError):
            reg.for_scenario("scenario_9")


# ---------------------------------------------------------------------------
# Loader failure modes (validation drift)
# ---------------------------------------------------------------------------


class TestLoaderValidation:
    def test_rejects_non_internal_tool_name(self, tmp_path):
        raw = _valid_stub()
        raw["scenarios"]["scenario_1"]["tools"][0]["name"] = "external.foo"
        p = tmp_path / "reg.json"
        p.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(ValidationError):
            load_tool_registry(p)

    def test_rejects_required_missing_from_properties(self, tmp_path):
        raw = _valid_stub()
        raw["scenarios"]["scenario_1"]["tools"][0]["parameters"]["required"] = [
            "not_declared",
        ]
        p = tmp_path / "reg.json"
        p.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(ValidationError):
            load_tool_registry(p)

    def test_rejects_missing_scenario(self, tmp_path):
        raw = _valid_stub()
        raw["scenarios"].pop("scenario_5")
        p = tmp_path / "reg.json"
        p.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(ValidationError):
            load_tool_registry(p)

    def test_rejects_extra_scenario(self, tmp_path):
        raw = _valid_stub()
        raw["scenarios"]["scenario_bogus"] = {
            "business_label": "x", "tools": [],
        }
        p = tmp_path / "reg.json"
        p.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(ValidationError):
            load_tool_registry(p)


# ---------------------------------------------------------------------------
# A0/A3 联调 — schemas hand-off round-trip through LiteLLM tool use
# ---------------------------------------------------------------------------


class TestA0A3Handshake:
    """§1.11 闭合项 — the shapes we generate here have to be accepted by
    A0's `call_with_tools`. We don't send anything to a real model, but
    we exercise `FakeLiteLLMClient` which uses the same shape."""

    def test_every_non_empty_scenario_hands_off_cleanly(self):
        reg = load_tool_registry()
        fake = FakeLiteLLMClient()
        for scenario_id in ("scenario_1", "scenario_2", "scenario_3",
                            "scenario_4"):
            schemas = reg.function_schemas_for(scenario_id)
            assert schemas, f"{scenario_id} unexpectedly empty"
            result = fake.call_with_tools(
                "primary-llm",
                messages=[{"role": "user", "content": "smoke"}],
                tools=schemas,
            )
            # Fake picks first tool + empty args by design; the check
            # here is just "no shape error when constructing the call".
            assert result.tool_calls
            assert result.tool_calls[0].name == schemas[0]["function"]["name"]

    def test_scenario_5_no_tools_returns_stop(self):
        reg = load_tool_registry()
        fake = FakeLiteLLMClient()
        result = fake.call_with_tools(
            "primary-llm",
            messages=[{"role": "user", "content": "smoke"}],
            tools=reg.function_schemas_for("scenario_5"),  # []
        )
        assert result.tool_calls == []
        assert result.finish_reason == "stop"


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _valid_stub() -> dict:
    """Load the shipped registry as a mutable dict so per-test tweaks
    exercise specific validators without hand-writing the whole JSON."""
    with open(
        Path(__file__).parents[3] / "config" / "query_router_tools.json",
        encoding="utf-8",
    ) as fh:
        return copy.deepcopy(json.load(fh))
