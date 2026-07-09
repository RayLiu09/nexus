"""Tests for AIPromptProfile seeding in the LLM classifier v2.

Verifies:
- first-use bootstrap creates an active profile with the shipped
  SYSTEM_PROMPT (idempotent seed),
- an already-active profile is returned unchanged,
- ``force_reseed=True`` archives the current profile and installs v+1.
"""

from __future__ import annotations

from sqlalchemy import select

from nexus_app import models
from nexus_app.enums import PromptProfileStatus
from nexus_app.knowledge_outline.llm_classifier import (
    PROMPT_PROFILE_DOMAIN,
    PROMPT_PROFILE_NAME,
    PROMPT_PROFILE_SCENARIO,
    PROMPT_PROFILE_TASK_TYPE,
    SYSTEM_PROMPT,
    ensure_knowledge_outline_prompt_profile,
)


def _list_profiles(session, scenario: str = PROMPT_PROFILE_SCENARIO):
    return list(session.scalars(
        select(models.AIPromptProfile)
        .where(models.AIPromptProfile.scenario == scenario)
        .order_by(models.AIPromptProfile.profile_version.asc())
    ))


def test_first_use_creates_active_profile(session):
    assert _list_profiles(session) == []
    profile = ensure_knowledge_outline_prompt_profile(
        session, default_model_alias="doubao-lite-heading",
    )
    session.commit()

    assert profile.profile_name == PROMPT_PROFILE_NAME
    assert profile.scenario == PROMPT_PROFILE_SCENARIO
    assert profile.task_type == PROMPT_PROFILE_TASK_TYPE
    assert profile.domain == PROMPT_PROFILE_DOMAIN
    assert profile.status == PromptProfileStatus.ACTIVE
    assert profile.profile_version == 1
    assert profile.prompt_template == SYSTEM_PROMPT
    assert profile.litellm_model_alias == "doubao-lite-heading"
    assert profile.temperature == 0.1

    rows = _list_profiles(session)
    assert len(rows) == 1
    assert rows[0].id == profile.id


def test_repeated_calls_return_same_active_profile(session):
    p1 = ensure_knowledge_outline_prompt_profile(
        session, default_model_alias="alias-1",
    )
    session.commit()
    p2 = ensure_knowledge_outline_prompt_profile(
        session, default_model_alias="alias-2-would-be-ignored",
    )
    assert p1.id == p2.id
    assert p2.litellm_model_alias == "alias-1"
    rows = _list_profiles(session)
    assert len(rows) == 1


def test_force_reseed_archives_prior_and_installs_next_version(session):
    p1 = ensure_knowledge_outline_prompt_profile(
        session, default_model_alias="alias-1",
    )
    session.commit()
    p2 = ensure_knowledge_outline_prompt_profile(
        session, default_model_alias="alias-2", force_reseed=True,
    )
    session.commit()

    rows = _list_profiles(session)
    assert len(rows) == 2
    assert p1.status == PromptProfileStatus.ARCHIVED
    assert p2.status == PromptProfileStatus.ACTIVE
    assert p2.profile_version == 2
    assert p2.litellm_model_alias == "alias-2"


def test_operator_edited_profile_wins_after_seed(session):
    # Operator installs a custom active profile via the console — the
    # bootstrap seed must not clobber it on subsequent calls.
    session.add(models.AIPromptProfile(
        profile_name=PROMPT_PROFILE_NAME,
        profile_version=7,
        task_type=PROMPT_PROFILE_TASK_TYPE,
        scenario=PROMPT_PROFILE_SCENARIO,
        domain=PROMPT_PROFILE_DOMAIN,
        status=PromptProfileStatus.ACTIVE,
        litellm_model_alias="operator-tuned",
        prompt_version="v2-operator",
        prompt_template="operator custom template",
        temperature=0.05,
        max_input_tokens=8192,
        redaction_policy="masked_content",
        output_schema_version="1.0",
        created_by="operator",
    ))
    session.commit()

    resolved = ensure_knowledge_outline_prompt_profile(
        session, default_model_alias="ignored",
    )
    assert resolved.litellm_model_alias == "operator-tuned"
    assert resolved.prompt_template == "operator custom template"
    assert resolved.profile_version == 7
