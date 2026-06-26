"""Seed fixtures shared by `tests/e2e/pipeline_b/*`.

The shared test session (`tests/conftest.py::session`) creates a fresh
schema per test — alembic seed migrations (0044 PGSD profile, 0047
ai_analysis_rules + prompt_profile) do NOT run. The acceptance tests
need those rows to exercise the full chain, so we seed them in a
session-autouse fixture here.

Seeding is per-test (function scope) because the parent `session`
fixture is function-scoped — the rows would otherwise vanish between
cases.
"""
from __future__ import annotations

import pytest

from nexus_app import models
from nexus_app.enums import PromptProfileStatus
from nexus_app.knowledge_extraction import seed_ai_analysis_rules


_PGSD_CATEGORY_SCHEMA = [
    {"code": "P", "name": "职业能力", "alias": ["职业技能"]},
    {"code": "G", "name": "通用能力"},
    {"code": "S", "name": "社会能力"},
    {"code": "D", "name": "发展能力"},
]
_PGSD_CODE_PATTERN = {
    "P": {"regex": r"^P-\d+\.\d+\.\d+$", "segments": 3,
          "requires_work_content": True},
    "G": {"regex": r"^G-\d+\.\d+$", "segments": 2,
          "requires_work_content": False},
    "S": {"regex": r"^S-\d+\.\d+$", "segments": 2,
          "requires_work_content": False},
    "D": {"regex": r"^D-\d+\.\d+$", "segments": 2,
          "requires_work_content": False},
}

_PROMPT_SEEDS = [
    ("occupation.job_demand.requirement_extraction",
     "knowledge_extraction", "job_demand_requirement_extraction",
     "occupation.job_demand.requirement_extraction.rules:v1"),
    ("occupation.task_description_structuring",
     "knowledge_extraction", "occupational_task_description_structuring",
     "occupation.task_description_structuring.rules:v1"),
    ("occupation.job_demand.body_markdown_render",
     "body_markdown_render", "job_demand_body_markdown_render",
     "occupation.job_demand.body_markdown_render.rules:v1"),
    ("occupation.ability_analysis.body_markdown_render",
     "body_markdown_render", "ability_analysis_body_markdown_render",
     "occupation.ability_analysis.body_markdown_render.rules:v1"),
]


@pytest.fixture(autouse=True)
def _seed_pipeline_b_runtime_rows(session):
    """Insert the PGSD profile + ai_analysis_rules + prompt profiles that
    B6 / B5.3 / B7 expect at runtime.

    The corresponding alembic migrations (0044 / 0047) populate these in
    production but don't fire under the test session — without this
    fixture every acceptance test would skip on `profile_not_found` /
    `rule_set_not_seeded`.
    """
    # PGSD profile (B6 writer + B7 governance dependency).
    session.add(models.AbilityAnalysisProfile(
        id="prof-pgsd-test",
        model_code="PGSD",
        model_name="PGSD",
        schema_version="ability_analysis.pgsd.v1",
        category_schema=_PGSD_CATEGORY_SCHEMA,
        code_pattern=_PGSD_CODE_PATTERN,
        is_active=True,
        is_builtin=True,
        initialized_by="acceptance_test_seed",
    ))

    # ai_analysis_rules (B5.2 / B5.3 / B5.4 dependency).
    seed_ai_analysis_rules(session)

    # Matching prompt profiles (B5.3 needs at least the markdown ones so
    # the deterministic fallback path can resolve a prompt_profile_id;
    # without a profile the renderer skips with prompt_profile_not_seeded
    # which means body_markdown stays None).
    for name, task_type, scenario, rules_code in _PROMPT_SEEDS:
        session.add(models.AIPromptProfile(
            profile_name=name,
            profile_version=1,
            task_type=task_type,
            scenario=scenario,
            domain="occupation",
            rules_object_type="ai_analysis_rules",
            rules_object_code=rules_code,
            status=PromptProfileStatus.ACTIVE,
            litellm_model_alias="internal/acceptance-stub",
            prompt_version="1.0",
            prompt_template=f"acceptance stub for {scenario}",
            temperature=0.0,
            max_input_tokens=8192,
            redaction_policy="masked_content",
            created_by="acceptance_test_seed",
        ))
    session.commit()
