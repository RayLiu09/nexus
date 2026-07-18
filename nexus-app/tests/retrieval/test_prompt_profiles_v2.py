"""B1 (§10 阶段 B) — retrieval v2 prompt profile seed + accessor tests.

Verifies:
* `seed_retrieval_v2_prompts` inserts 4 profiles under distinct names.
* Idempotent — a second call doesn't create duplicate rows or bump
  the version counter.
* Every seeded profile is retrievable via `get_active_v2_prompt`.
* Prompt templates carry the placeholders the dispatcher / composer /
  extractor rely on (contract test — a maintainer accidentally
  removing `{{PARAMS_SCHEMA}}` would break Layer 1 parameter extraction).
* Intent template lists all 5 scenario ids in the §1.15 business-view
  form.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from nexus_app import models
from nexus_app.enums import PromptProfileStatus
from nexus_app.retrieval.prompt_profiles_v2 import (
    COMPOSE_V2_PROFILE_NAME,
    COMPOSE_V2_PROMPT_TEMPLATE,
    INTENT_V2_PROFILE_NAME,
    INTENT_V2_PROMPT_TEMPLATE,
    PARAM_EXTRACT_V2_PROFILE_NAME,
    PARAM_EXTRACT_V2_PROMPT_TEMPLATE,
    QUERY_EXPANSION_V2_PROFILE_NAME,
    QUERY_EXPANSION_V2_PROMPT_TEMPLATE,
    RETRIEVAL_V2_TASK_TYPE,
    get_active_v2_prompt,
    seed_retrieval_v2_prompts,
)


_ALL_PROFILE_NAMES = {
    INTENT_V2_PROFILE_NAME,
    PARAM_EXTRACT_V2_PROFILE_NAME,
    COMPOSE_V2_PROFILE_NAME,
    QUERY_EXPANSION_V2_PROFILE_NAME,
}


# ---------------------------------------------------------------------------
# Seed lifecycle
# ---------------------------------------------------------------------------


class TestSeed:
    def test_seed_inserts_four_active_profiles(self, session):
        result = seed_retrieval_v2_prompts(session)
        session.commit()

        assert set(result) == _ALL_PROFILE_NAMES
        for name in _ALL_PROFILE_NAMES:
            profile = result[name]
            assert profile.status == PromptProfileStatus.ACTIVE
            assert profile.task_type == RETRIEVAL_V2_TASK_TYPE
            assert profile.profile_version == 1
            assert profile.output_schema_version == "v2.0.1"

    def test_seed_is_idempotent(self, session):
        first = seed_retrieval_v2_prompts(session)
        session.commit()
        second = seed_retrieval_v2_prompts(session)
        session.commit()

        # Same profile ids returned — no duplicate rows inserted.
        for name in _ALL_PROFILE_NAMES:
            assert first[name].id == second[name].id

        # Only 4 rows total in the table (one per profile name).
        rows = list(session.scalars(select(models.AIPromptProfile)))
        assert len(rows) == 4

    def test_seed_preserves_console_edits(self, session):
        """If a console user has already updated a profile, `seed_*`
        must not clobber the newer version — it's a first-run helper,
        not a reset."""
        from nexus_app.ai_governance.services import PromptProfileService

        # First seed the defaults.
        seed_retrieval_v2_prompts(session)
        session.commit()

        # Simulate a console edit that bumps the version of intent_v2.
        service = PromptProfileService()
        service.update_profile(
            session,
            profile_name=INTENT_V2_PROFILE_NAME,
            prompt_template="edited by console",
        )
        session.commit()

        # Re-run the seed — the edited version must survive.
        seed_retrieval_v2_prompts(session)
        session.commit()

        active = get_active_v2_prompt(session, INTENT_V2_PROFILE_NAME)
        assert active.prompt_template == "edited by console"
        assert active.profile_version == 2

    def test_temperatures_are_scenario_appropriate(self, session):
        result = seed_retrieval_v2_prompts(session)
        session.commit()
        # Deterministic tasks — intent & param extract — must run cold.
        assert result[INTENT_V2_PROFILE_NAME].temperature == 0.0
        assert result[PARAM_EXTRACT_V2_PROFILE_NAME].temperature == 0.0
        # Generative tasks tolerate mild sampling for variety.
        assert result[COMPOSE_V2_PROFILE_NAME].temperature == 0.3
        assert result[QUERY_EXPANSION_V2_PROFILE_NAME].temperature == 0.3


# ---------------------------------------------------------------------------
# Accessor
# ---------------------------------------------------------------------------


class TestAccessor:
    def test_get_active_v2_prompt_returns_seeded_row(self, session):
        seed_retrieval_v2_prompts(session)
        session.commit()

        profile = get_active_v2_prompt(session, INTENT_V2_PROFILE_NAME)
        assert profile.profile_name == INTENT_V2_PROFILE_NAME
        assert profile.status == PromptProfileStatus.ACTIVE

    def test_get_active_v2_prompt_raises_when_missing(self, session):
        with pytest.raises(LookupError, match="No active ai_prompt_profile"):
            get_active_v2_prompt(session, INTENT_V2_PROFILE_NAME)


# ---------------------------------------------------------------------------
# Prompt content contract
# ---------------------------------------------------------------------------


class TestPromptContent:
    def test_intent_template_lists_five_business_scenarios(self):
        """The dispatcher pins the enum values it accepts; the prompt
        MUST list every one so the LLM's output actually maps to a
        real scenario id."""
        for scenario_id in ("scenario_1", "scenario_2", "scenario_3",
                            "scenario_4", "scenario_5"):
            assert scenario_id in INTENT_V2_PROMPT_TEMPLATE
        # §1.15 business-view labels — a docs regression that reverts
        # to the v2.0 "综合性检索" wording surfaces here.
        assert "讯息类" in INTENT_V2_PROMPT_TEMPLATE
        assert "结构化数据" in INTENT_V2_PROMPT_TEMPLATE
        assert "教学标准" in INTENT_V2_PROMPT_TEMPLATE
        assert "教材类" in INTENT_V2_PROMPT_TEMPLATE
        assert "Agentic RAG" in INTENT_V2_PROMPT_TEMPLATE
        # Confidence threshold contract — see §4.1.1.
        assert "0.6" in INTENT_V2_PROMPT_TEMPLATE

    def test_intent_template_carries_query_placeholder(self):
        assert "{{QUERY}}" in INTENT_V2_PROMPT_TEMPLATE

    def test_param_extract_template_placeholders(self):
        # All three inputs the extractor injects.
        for placeholder in ("{{QUERY}}", "{{INTENT}}", "{{PARAMS_SCHEMA}}"):
            assert placeholder in PARAM_EXTRACT_V2_PROMPT_TEMPLATE
        # Output contract fields.
        assert "extracted_params" in PARAM_EXTRACT_V2_PROMPT_TEMPLATE
        assert "missing_required" in PARAM_EXTRACT_V2_PROMPT_TEMPLATE

    def test_compose_template_placeholders(self):
        for placeholder in ("{{QUERY}}", "{{INTENT}}",
                            "{{TOOL_RESULTS}}", "{{CHART_PLACEHOLDERS}}"):
            assert placeholder in COMPOSE_V2_PROMPT_TEMPLATE
        # Generated-block wrapper contract (§4.3).
        assert "⚠️" in COMPOSE_V2_PROMPT_TEMPLATE
        assert "[[CHART:" in COMPOSE_V2_PROMPT_TEMPLATE
        assert "[^ref" in COMPOSE_V2_PROMPT_TEMPLATE

    def test_query_expansion_template_placeholders(self):
        assert "{{QUERY}}" in QUERY_EXPANSION_V2_PROMPT_TEMPLATE
        # Provider clip range (see A5 defaults).
        assert "3" in QUERY_EXPANSION_V2_PROMPT_TEMPLATE
        assert "5" in QUERY_EXPANSION_V2_PROMPT_TEMPLATE
