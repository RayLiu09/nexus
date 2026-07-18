"""B2 (§10 阶段 B) — IntentClassifierV2 tests.

Uses a scripted LiteLLM stub so no network / real model is needed. The
prompt profile row is seeded by `seed_retrieval_v2_prompts` (verified
in B1 tests).

Coverage:
* Happy path: model returns a valid scenario id + high confidence.
* Every valid scenario id (`scenario_1..5` + `unknown`) round-trips.
* Confidence below threshold → `low_confidence=True` but intent kept.
* Explicit `unknown` from model → no fallback reason.
* Malformed JSON → `unknown` with `fallback_reason="output_parse_failed"`.
* Malformed schema (missing confidence) → same fallback.
* LLM raises → `unknown` with `fallback_reason="llm_call_failed"`.
* Empty query → `unknown` short-circuit before LLM call.
* Missing prompt profile → `unknown` with `fallback_reason="prompt_profile_missing"`.
* Unknown-ish label (`SCENARIO_1`, `Scenario_1`, mystery values) coerced.
* Query text with curly braces / `%s` doesn't crash the prompt build.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from nexus_app.ai_governance.litellm_client import (
    FakeLiteLLMClient,
    LiteLLMCallError,
    LiteLLMErrorType,
)
from nexus_app.retrieval.intent_v2 import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    IntentClassifierV2,
    IntentV2Result,
)
from nexus_app.retrieval.prompt_profiles_v2 import seed_retrieval_v2_prompts


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def seeded_session(session):
    """Session with the v2 prompt profiles pre-seeded."""
    seed_retrieval_v2_prompts(session)
    session.commit()
    return session


class _ScriptedLLM:
    """LiteLLM stub that returns a fixed JSON string on `.call()` and
    optionally raises `LiteLLMCallError` first."""

    def __init__(
        self,
        response_content: str = "",
        *,
        raise_error: LiteLLMCallError | None = None,
    ) -> None:
        self._content = response_content
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
        return self._content, SimpleNamespace(
            request_id="fake",
            model_alias=model_alias,
        )

    def call_with_tools(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError


def _json(intent: str, confidence: float) -> str:
    return json.dumps({"intent": intent, "confidence": confidence})


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_high_confidence_scenario_1_passes_through(self, seeded_session):
        llm = _ScriptedLLM(_json("scenario_1", 0.92))
        classifier = IntentClassifierV2(llm_client=llm)

        result = classifier.classify(seeded_session, "跨境电商行业趋势报告")

        assert result.intent == "scenario_1"
        assert result.confidence == 0.92
        assert result.low_confidence is False
        assert result.fallback_reason is None
        # Prompt template was filled with the actual query.
        rendered = llm.calls[0]["messages"][0]["content"]
        assert "跨境电商行业趋势报告" in rendered
        assert "{{QUERY}}" not in rendered  # placeholder replaced

    @pytest.mark.parametrize("scenario_id", [
        "scenario_1", "scenario_2", "scenario_3",
        "scenario_4", "scenario_5",
    ])
    def test_all_valid_scenarios_round_trip(self, seeded_session, scenario_id):
        llm = _ScriptedLLM(_json(scenario_id, 0.85))
        classifier = IntentClassifierV2(llm_client=llm)
        result = classifier.classify(seeded_session, "any query")
        assert result.intent == scenario_id

    def test_explicit_unknown_carries_no_fallback_reason(self, seeded_session):
        """A model that explicitly picks `unknown` is answering the
        classifier's question, not fallbackING — the dispatcher should
        see this as a legitimate call, not a system error."""
        llm = _ScriptedLLM(_json("unknown", 0.4))
        classifier = IntentClassifierV2(llm_client=llm)
        result = classifier.classify(seeded_session, "无法归类的问题")
        assert result.intent == "unknown"
        assert result.confidence == 0.4
        assert result.fallback_reason is None


# ---------------------------------------------------------------------------
# Confidence threshold
# ---------------------------------------------------------------------------


class TestConfidenceThreshold:
    def test_low_confidence_kept_but_flagged(self, seeded_session):
        llm = _ScriptedLLM(_json("scenario_2", 0.3))
        classifier = IntentClassifierV2(
            llm_client=llm, confidence_threshold=0.6,
        )
        result = classifier.classify(seeded_session, "岗位需求")
        assert result.intent == "scenario_2"
        assert result.confidence == 0.3
        assert result.low_confidence is True

    def test_confidence_equal_to_threshold_is_high_confidence(self, seeded_session):
        llm = _ScriptedLLM(_json("scenario_4", 0.6))
        classifier = IntentClassifierV2(
            llm_client=llm, confidence_threshold=0.6,
        )
        result = classifier.classify(seeded_session, "教材知识点")
        assert result.low_confidence is False

    def test_custom_threshold_respected(self, seeded_session):
        llm = _ScriptedLLM(_json("scenario_2", 0.5))
        classifier = IntentClassifierV2(
            llm_client=llm, confidence_threshold=0.4,
        )
        result = classifier.classify(seeded_session, "岗位需求")
        assert result.low_confidence is False

    def test_default_threshold_matches_design_doc(self):
        """§4.1.1 pins the default at 0.6 — a maintainer bumping it
        by accident surfaces here."""
        assert DEFAULT_CONFIDENCE_THRESHOLD == 0.6


# ---------------------------------------------------------------------------
# Failure paths (all return unknown + fallback_reason)
# ---------------------------------------------------------------------------


class TestFailurePaths:
    def test_malformed_json_falls_back(self, seeded_session):
        llm = _ScriptedLLM("this is not json")
        classifier = IntentClassifierV2(llm_client=llm)
        result = classifier.classify(seeded_session, "q")
        assert result.intent == "unknown"
        assert result.confidence == 0.0
        assert result.fallback_reason == "output_parse_failed"

    def test_schema_mismatch_missing_confidence(self, seeded_session):
        llm = _ScriptedLLM(json.dumps({"intent": "scenario_1"}))
        classifier = IntentClassifierV2(llm_client=llm)
        result = classifier.classify(seeded_session, "q")
        assert result.intent == "unknown"
        assert result.fallback_reason == "output_parse_failed"

    def test_schema_mismatch_confidence_out_of_range(self, seeded_session):
        llm = _ScriptedLLM(_json("scenario_1", 1.5))
        classifier = IntentClassifierV2(llm_client=llm)
        result = classifier.classify(seeded_session, "q")
        assert result.intent == "unknown"
        assert result.fallback_reason == "output_parse_failed"

    def test_llm_call_error_falls_back(self, seeded_session):
        llm = _ScriptedLLM(
            "unused",
            raise_error=LiteLLMCallError("timeout", LiteLLMErrorType.TIMEOUT),
        )
        classifier = IntentClassifierV2(llm_client=llm)
        result = classifier.classify(seeded_session, "q")
        assert result.intent == "unknown"
        assert result.fallback_reason == "llm_call_failed"
        assert "timeout" in result.warnings

    def test_empty_query_short_circuits(self, seeded_session):
        llm = _ScriptedLLM(_json("scenario_1", 0.99))
        classifier = IntentClassifierV2(llm_client=llm)
        result = classifier.classify(seeded_session, "")
        assert result.intent == "unknown"
        assert result.fallback_reason == "empty_query"
        assert llm.calls == []  # No LLM call for empty query

    def test_whitespace_only_query_short_circuits(self, seeded_session):
        llm = _ScriptedLLM(_json("scenario_1", 0.99))
        classifier = IntentClassifierV2(llm_client=llm)
        result = classifier.classify(seeded_session, "   \n  \t")
        assert result.intent == "unknown"
        assert result.fallback_reason == "empty_query"

    def test_missing_prompt_profile_falls_back(self, session):
        """No seed = no active row = fallback (empty session)."""
        llm = _ScriptedLLM(_json("scenario_1", 0.99))
        classifier = IntentClassifierV2(llm_client=llm)
        result = classifier.classify(session, "q")
        assert result.intent == "unknown"
        assert result.fallback_reason == "prompt_profile_missing"


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


class TestRobustness:
    def test_uppercase_intent_coerced_to_lowercase(self, seeded_session):
        llm = _ScriptedLLM(_json("SCENARIO_1", 0.9))
        classifier = IntentClassifierV2(llm_client=llm)
        result = classifier.classify(seeded_session, "q")
        assert result.intent == "scenario_1"

    def test_mixed_case_intent_coerced(self, seeded_session):
        llm = _ScriptedLLM(_json("Scenario_3", 0.9))
        classifier = IntentClassifierV2(llm_client=llm)
        result = classifier.classify(seeded_session, "q")
        assert result.intent == "scenario_3"

    def test_intent_with_whitespace_coerced(self, seeded_session):
        llm = _ScriptedLLM(_json("  scenario_2  ", 0.9))
        classifier = IntentClassifierV2(llm_client=llm)
        result = classifier.classify(seeded_session, "q")
        assert result.intent == "scenario_2"

    def test_rogue_intent_label_coerced_to_unknown(self, seeded_session):
        """LLM hallucinated a scenario name we don't recognise —
        must not leak into dispatcher which would 404 on the enum."""
        llm = _ScriptedLLM(_json("scenario_42", 0.9))
        classifier = IntentClassifierV2(llm_client=llm)
        result = classifier.classify(seeded_session, "q")
        assert result.intent == "unknown"
        # Not a system failure — the model produced parseable JSON,
        # just an invalid enum value. `fallback_reason` stays None.
        assert result.fallback_reason is None

    def test_query_with_curly_braces_does_not_crash_prompt_build(
        self, seeded_session,
    ):
        """`str.replace` is safe against `{}` chars; `str.format` would
        crash. Guard for user queries containing code snippets or JSON."""
        llm = _ScriptedLLM(_json("scenario_1", 0.9))
        classifier = IntentClassifierV2(llm_client=llm)
        result = classifier.classify(
            seeded_session,
            'find rows where {"id": 1} matches — no {crash} please',
        )
        assert result.intent == "scenario_1"
        rendered = llm.calls[0]["messages"][0]["content"]
        assert '{"id": 1}' in rendered

    def test_uses_prompt_profile_model_alias_and_temperature(
        self, seeded_session,
    ):
        llm = _ScriptedLLM(_json("scenario_1", 0.9))
        classifier = IntentClassifierV2(llm_client=llm)
        classifier.classify(seeded_session, "q")
        call = llm.calls[0]
        # Seeded template runs intent classification at temperature 0
        # (see prompt_profiles_v2 spec — deterministic classification).
        assert call["kwargs"]["temperature"] == 0.0
        # LiteLLM alias comes from the profile, not a hardcoded value.
        assert call["model_alias"]  # sanity — any non-empty string
        # response_format asked for JSON.
        assert call["kwargs"]["response_format"] == {"type": "json_object"}


# ---------------------------------------------------------------------------
# Integration smoke — the real FakeLiteLLMClient response is a demo
# governance blob, so intent must fall back to unknown/parse-failed.
# Documents the current behaviour so the default fake doesn't sneak past.
# ---------------------------------------------------------------------------


def test_default_fake_client_falls_back_because_response_is_governance_shape(
    seeded_session,
):
    """`FakeLiteLLMClient` (no override) returns the demo governance
    JSON (classification/level/tags). That is NOT the intent v2 output
    shape, so the classifier should fall back to unknown/parse_failed.
    Nailing this in a test prevents accidental green tests where
    someone forgets to override the fake with an intent-shaped response.
    """
    llm = FakeLiteLLMClient()
    classifier = IntentClassifierV2(llm_client=llm)
    result = classifier.classify(seeded_session, "q")
    assert result.intent == "unknown"
    # governance blob HAS `confidence`, but no `intent` field →
    # schema mismatch.
    assert result.fallback_reason == "output_parse_failed"
