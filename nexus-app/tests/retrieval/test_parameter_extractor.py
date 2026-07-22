"""B3 (§10 阶段 B) — ParameterExtractorV2 + build_union_schema tests.

Two independent surfaces:

* `build_union_schema` — pure function; unit-test with hand-built
  `ToolSpec` fixtures so we don't need the DB or the registry file.
* `ParameterExtractorV2.extract` — end-to-end with the seeded prompt
  profile + default tool registry (loaded from
  `config/query_router_tools.json`).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from nexus_app.ai_governance.litellm_client import (
    LiteLLMCallError,
    LiteLLMErrorType,
)
from nexus_app.retrieval.parameter_extractor import (
    ParameterExtractorV2,
    build_union_schema,
)
from nexus_app.retrieval.prompt_profiles_v2 import seed_retrieval_v2_prompts
from nexus_app.retrieval.tools_registry import ToolSpec


# ---------------------------------------------------------------------------
# build_union_schema — pure function
# ---------------------------------------------------------------------------


def _tool(name: str, properties: dict, required: list[str]) -> ToolSpec:
    return ToolSpec.model_validate({
        "name": name,
        "description": "test tool",
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    })


class TestBuildUnionSchema:
    def test_empty_tool_list_yields_empty_schema(self):
        schema = build_union_schema([])
        assert schema == {
            "type": "object",
            "properties": {},
            "required": [],
        }

    def test_single_tool_shape_preserved(self):
        tool = _tool(
            "internal.demo",
            {"major": {"type": "string"}, "top_k": {"type": "integer"}},
            ["major"],
        )
        schema = build_union_schema([tool])
        assert schema["properties"].keys() == {"major", "top_k"}
        assert schema["required"] == ["major"]

    def test_first_tool_wins_on_property_conflict(self):
        """Two tools defining `top_k` with different types — the
        first tool in the list wins so dispatch is deterministic."""
        t1 = _tool("internal.a", {"top_k": {"type": "integer"}}, [])
        t2 = _tool("internal.b", {"top_k": {"type": "string"}}, [])
        schema = build_union_schema([t1, t2])
        assert schema["properties"]["top_k"] == {"type": "integer"}

    def test_field_required_by_all_tools_stays_required(self):
        t1 = _tool("internal.a", {"query": {"type": "string"}}, ["query"])
        t2 = _tool("internal.b", {"query": {"type": "string"}}, ["query"])
        schema = build_union_schema([t1, t2])
        assert schema["required"] == ["query"]

    def test_field_optional_in_any_tool_drops_from_required(self):
        """`major_name` required by tool A, optional by tool B → union
        keeps it optional (dispatcher can call tool B without it)."""
        t1 = _tool("internal.a",
                    {"major_name": {"type": "string"}}, ["major_name"])
        t2 = _tool("internal.b",
                    {"major_name": {"type": "string"}}, [])
        schema = build_union_schema([t1, t2])
        assert "major_name" in schema["properties"]
        assert schema["required"] == []

    def test_required_only_when_declared_by_every_tool(self):
        """`year` required by tool A, tool B doesn't declare it at all →
        not scenario-level required. The dispatcher validates selected-tool
        required fields after the scenario sub-domain is known."""
        t1 = _tool("internal.a",
                    {"year": {"type": "integer"}}, ["year"])
        t2 = _tool("internal.b",
                    {"other": {"type": "string"}}, [])
        schema = build_union_schema([t1, t2])
        assert "year" in schema["properties"]
        assert schema["required"] == []


# ---------------------------------------------------------------------------
# ParameterExtractorV2 — end-to-end with scripted LLM
# ---------------------------------------------------------------------------


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
        return self._response, SimpleNamespace(request_id="fake")

    def call_with_tools(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError


@pytest.fixture()
def seeded_session(session):
    seed_retrieval_v2_prompts(session)
    session.commit()
    return session


def _resp(extracted: dict, missing: list[str] | None = None) -> str:
    return json.dumps({
        "extracted_params": extracted,
        "missing_required": missing or [],
    })


class TestExtractorHappyPath:
    def test_scenario_2_query_yields_major_name(self, seeded_session):
        """scenario_2 tools union — major (query_job_demand) +
        major_name (query_capability_graph_by_major) + others. We
        return `major_name=跨境电商` from the LLM and assert it
        surfaces."""
        llm = _ScriptedLLM(_resp({"major_name": "跨境电商"}))
        extractor = ParameterExtractorV2(llm_client=llm)

        result = extractor.extract(
            seeded_session,
            query="跨境电商的岗位需求分布如何？",
            intent="scenario_2",
        )

        assert result.extracted_params == {"major_name": "跨境电商"}
        # scenario_2 is a mixed-tool scenario. Fields required by only
        # one branch (job_title / build_type / major) must not become
        # scenario-level missing parameters.
        assert result.missing_required == []
        # LLM saw a real schema with scenario_2 properties.
        prompt_content = llm.calls[0]["messages"][0]["content"]
        assert "跨境电商的岗位需求分布如何？" in prompt_content
        assert "scenario_2" in prompt_content

    def test_scenario_1_query_extracts_top_k_and_expand_queries(
        self, seeded_session,
    ):
        llm = _ScriptedLLM(_resp({
            "query": "2025 年跨境电商政策",
            "top_k": 8,
            "expand_queries": True,
        }))
        extractor = ParameterExtractorV2(llm_client=llm)

        result = extractor.extract(
            seeded_session,
            query="2025 年跨境电商政策",
            intent="scenario_1",
        )
        assert result.extracted_params["query"] == "2025 年跨境电商政策"
        assert result.extracted_params["top_k"] == 8
        assert result.extracted_params["expand_queries"] is True


class TestExtractorMissingRequired:
    def test_reports_missing_required_field(self, seeded_session):
        """scenario_1's `search_chunks_by_semantic` marks `query`
        required. If the LLM doesn't extract it, missing_required
        must call it out so the dispatcher can prompt the user."""
        llm = _ScriptedLLM(_resp({}))  # nothing extracted
        extractor = ParameterExtractorV2(llm_client=llm)
        result = extractor.extract(
            seeded_session, query="something", intent="scenario_1",
        )
        assert "query" in result.missing_required

    def test_llm_missing_required_intersected_with_schema(self, seeded_session):
        """If the LLM invents a `missing_required` entry that isn't in
        the union schema, we drop it — the dispatcher shouldn't
        prompt for a phantom field."""
        llm = _ScriptedLLM(_resp(
            {"query": "q"},
            missing=["query", "phantom_field"],
        ))
        extractor = ParameterExtractorV2(llm_client=llm)
        result = extractor.extract(
            seeded_session, query="q", intent="scenario_1",
        )
        # `query` was extracted → NOT missing.
        # `phantom_field` isn't in the schema → drop from missing.
        assert result.missing_required == []


class TestExtractorNullHandling:
    def test_null_values_dropped_from_extracted_params(self, seeded_session):
        llm = _ScriptedLLM(_resp({
            "query": "q",
            "top_k": None,   # LLM said "not mentioned"
            "kb": None,
        }))
        extractor = ParameterExtractorV2(llm_client=llm)
        result = extractor.extract(
            seeded_session, query="q", intent="scenario_1",
        )
        assert result.extracted_params == {"query": "q"}
        assert "top_k" not in result.extracted_params
        assert "kb" not in result.extracted_params

    def test_hallucinated_field_not_in_schema_dropped(self, seeded_session):
        llm = _ScriptedLLM(_resp({
            "query": "q",
            "made_up_field": "shouldn't leak",
        }))
        extractor = ParameterExtractorV2(llm_client=llm)
        result = extractor.extract(
            seeded_session, query="q", intent="scenario_1",
        )
        assert "made_up_field" not in result.extracted_params


class TestExtractorFallbacks:
    def test_empty_query_short_circuits(self, seeded_session):
        llm = _ScriptedLLM(_resp({"query": "q"}))
        extractor = ParameterExtractorV2(llm_client=llm)
        result = extractor.extract(
            seeded_session, query="", intent="scenario_1",
        )
        assert result.fallback_reason == "empty_query"
        assert result.extracted_params == {}
        assert llm.calls == []

    def test_unknown_intent_short_circuits(self, seeded_session):
        llm = _ScriptedLLM(_resp({"query": "q"}))
        extractor = ParameterExtractorV2(llm_client=llm)
        result = extractor.extract(
            seeded_session, query="q", intent="unknown",
        )
        assert result.fallback_reason == "unknown_intent"
        assert llm.calls == []

    def test_scenario_5_has_no_tools_returns_no_tools_fallback(
        self, seeded_session,
    ):
        """scenario_5 (Agentic RAG) legitimately carries an empty
        tool list — the extractor should signal that state distinctly
        from `unknown_intent` so the dispatcher can route to the
        template executor."""
        llm = _ScriptedLLM(_resp({"query": "q"}))
        extractor = ParameterExtractorV2(llm_client=llm)
        result = extractor.extract(
            seeded_session, query="q", intent="scenario_5",
        )
        assert result.fallback_reason == "no_tools_for_intent"

    def test_unknown_scenario_id_treated_as_unknown_intent(self, seeded_session):
        llm = _ScriptedLLM(_resp({"query": "q"}))
        extractor = ParameterExtractorV2(llm_client=llm)
        result = extractor.extract(
            seeded_session, query="q", intent="scenario_99",
        )
        assert result.fallback_reason == "unknown_intent"

    def test_malformed_json_from_llm_falls_back(self, seeded_session):
        llm = _ScriptedLLM("not json")
        extractor = ParameterExtractorV2(llm_client=llm)
        result = extractor.extract(
            seeded_session, query="q", intent="scenario_1",
        )
        assert result.fallback_reason == "output_parse_failed"
        assert result.extracted_params == {}
        # Missing_required populated from the schema so the
        # dispatcher has something to prompt for.
        assert "query" in result.missing_required

    def test_llm_call_error_falls_back(self, seeded_session):
        llm = _ScriptedLLM(
            "",
            raise_error=LiteLLMCallError(
                "rate limit", LiteLLMErrorType.RATE_LIMIT,
            ),
        )
        extractor = ParameterExtractorV2(llm_client=llm)
        result = extractor.extract(
            seeded_session, query="q", intent="scenario_1",
        )
        assert result.fallback_reason == "llm_call_failed"
        assert "rate_limit" in result.warnings

    def test_missing_prompt_profile_falls_back(self, session):
        """Session with no seeded profile — extract must not raise,
        must produce a stable fallback with missing_required populated."""
        llm = _ScriptedLLM(_resp({"query": "q"}))
        extractor = ParameterExtractorV2(llm_client=llm)
        result = extractor.extract(
            session, query="q", intent="scenario_1",
        )
        assert result.fallback_reason == "prompt_profile_missing"
        # Schema still built from the registry, so dispatcher can
        # prompt for the required fields even without a working LLM.
        assert "query" in result.missing_required


class TestExtractorPromptBuild:
    def test_prompt_carries_query_intent_and_schema(self, seeded_session):
        llm = _ScriptedLLM(_resp({"query": "q"}))
        extractor = ParameterExtractorV2(llm_client=llm)
        extractor.extract(
            seeded_session,
            query="搜索跨境电商政策 top 8 条",
            intent="scenario_1",
        )
        content = llm.calls[0]["messages"][0]["content"]
        # All three placeholders were replaced.
        assert "{{QUERY}}" not in content
        assert "{{INTENT}}" not in content
        assert "{{PARAMS_SCHEMA}}" not in content
        # Real values landed.
        assert "搜索跨境电商政策 top 8 条" in content
        assert "scenario_1" in content
        # The union schema JSON was rendered.
        assert '"type": "object"' in content
        assert '"query"' in content  # scenario_1 required field

    def test_query_with_curly_braces_does_not_crash_prompt(
        self, seeded_session,
    ):
        llm = _ScriptedLLM(_resp({"query": "q"}))
        extractor = ParameterExtractorV2(llm_client=llm)
        extractor.extract(
            seeded_session,
            query='find rows where {"id": 1} matches',
            intent="scenario_1",
        )
        rendered = llm.calls[0]["messages"][0]["content"]
        assert '{"id": 1}' in rendered
