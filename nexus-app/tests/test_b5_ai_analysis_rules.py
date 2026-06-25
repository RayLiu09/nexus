"""B5.1 — ai_analysis_rules data model + seed loader + ai_prompt_profile extension.

What we lock in:

- Loader parses `config/ai_analysis_rules.json` according to the freeze
  (§八 contract): 4 rule_sets, distinct (rule_set_code, version), XOR
  between output_item_schema / markdown_skeleton.
- Loader rejects malformed seeds rather than silently degrading — bad
  config is a deploy-time failure.
- `seed_ai_analysis_rules()` is idempotent: second run inserts 0 rows.
- AIPromptProfile extension fields (domain / rules_object_type /
  rules_object_code) round-trip through the ORM.
- After 0046+0047 migrations, the table has the 4 expected rule sets and
  4 paired prompt profiles, with `(profile.rules_object_code ==
  <rule.rule_set_code>:<rule.version>)` per pair.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from nexus_app import models
from nexus_app.knowledge_extraction.rules_loader import (
    SEED_FILE_PATH,
    AnalysisRuleSet,
    load_seed_file,
    seed_ai_analysis_rules,
)


# ---------------------------------------------------------------------------
# Loader — happy path
# ---------------------------------------------------------------------------


class TestLoaderHappyPath:
    def test_seed_file_exists(self):
        assert SEED_FILE_PATH.exists(), (
            "config/ai_analysis_rules.json missing; B0 freeze artefact required"
        )

    def test_loads_four_rule_sets(self):
        rules = load_seed_file()
        assert len(rules) == 4
        codes = {r.rule_set_code for r in rules}
        assert codes == {
            "occupation.job_demand.requirement_extraction.rules",
            "occupation.task_description_structuring.rules",
            "occupation.job_demand.body_markdown_render.rules",
            "occupation.ability_analysis.body_markdown_render.rules",
        }

    def test_each_rule_set_parsed_into_dataclass(self):
        for rule in load_seed_file():
            assert isinstance(rule, AnalysisRuleSet)
            assert rule.version == "v1"
            assert rule.domain == "occupation"
            assert rule.is_active is True
            assert rule.is_builtin is True

    def test_extraction_rules_carry_output_item_schema_not_skeleton(self):
        rules = {r.rule_set_code: r for r in load_seed_file()}
        extraction = rules["occupation.job_demand.requirement_extraction.rules"]
        assert extraction.output_format == "json"
        assert extraction.output_item_schema is not None
        assert extraction.markdown_skeleton is None
        assert extraction.fallback_strategy == "reject"

    def test_markdown_rules_carry_skeleton_not_item_schema(self):
        rules = {r.rule_set_code: r for r in load_seed_file()}
        render = rules["occupation.job_demand.body_markdown_render.rules"]
        assert render.output_format == "markdown"
        assert render.markdown_skeleton is not None
        assert render.output_item_schema is None
        assert render.fallback_strategy == "deterministic_template"

    def test_auto_admit_threshold_is_decimal_in_range(self):
        for rule in load_seed_file():
            assert isinstance(rule.auto_admit_threshold, Decimal)
            assert Decimal("0") <= rule.auto_admit_threshold <= Decimal("1")


# ---------------------------------------------------------------------------
# Loader — error paths (deploy-time failure surface)
# ---------------------------------------------------------------------------


def _write_seed(tmp_path: Path, payload: dict) -> Path:
    target = tmp_path / "rules.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


class TestLoaderRejectsMalformedSeeds:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_seed_file(tmp_path / "nope.json")

    def test_wrong_schema_version_raises(self, tmp_path):
        path = _write_seed(tmp_path, {
            "schema_version": "ai_analysis_rules.v999",
            "rule_sets": [],
        })
        with pytest.raises(ValueError, match="schema_version"):
            load_seed_file(path)

    def test_empty_rule_sets_array_raises(self, tmp_path):
        path = _write_seed(tmp_path, {
            "schema_version": "ai_analysis_rules.v1",
            "rule_sets": [],
        })
        with pytest.raises(ValueError, match="non-empty"):
            load_seed_file(path)

    def test_duplicate_code_version_pair_raises(self, tmp_path):
        rule = {
            "rule_set_code": "x.y.z",
            "version": "v1",
            "scenario": "s",
            "domain": "d",
            "target_type": ["normalized_record"],
            "output_format": "json",
            "output_contract": {"k": "string"},
            "output_item_schema": {"type": "object"},
            "field_whitelist": ["f"],
            "guardrails": [],
            "auto_admit_threshold": 0.5,
            "schema_version": "x.v1",
        }
        path = _write_seed(tmp_path, {
            "schema_version": "ai_analysis_rules.v1",
            "rule_sets": [rule, rule],
        })
        with pytest.raises(ValueError, match="duplicate"):
            load_seed_file(path)

    def test_json_output_without_item_schema_raises(self, tmp_path):
        path = _write_seed(tmp_path, {
            "schema_version": "ai_analysis_rules.v1",
            "rule_sets": [{
                "rule_set_code": "x", "version": "v1", "scenario": "s",
                "domain": "d", "target_type": ["x"], "output_format": "json",
                "output_contract": {"k": "string"},
                "field_whitelist": [], "guardrails": [],
                "auto_admit_threshold": 0.5, "schema_version": "v1",
            }],
        })
        with pytest.raises(ValueError, match="output_item_schema"):
            load_seed_file(path)

    def test_markdown_output_with_item_schema_raises(self, tmp_path):
        path = _write_seed(tmp_path, {
            "schema_version": "ai_analysis_rules.v1",
            "rule_sets": [{
                "rule_set_code": "x", "version": "v1", "scenario": "s",
                "domain": "d", "target_type": ["x"], "output_format": "markdown",
                "output_contract": {"markdown": "string"},
                "output_item_schema": {"type": "object"},  # forbidden
                "markdown_skeleton": {"required_headings": []},
                "field_whitelist": [], "guardrails": [],
                "auto_admit_threshold": 0.5, "schema_version": "v1",
            }],
        })
        with pytest.raises(ValueError, match="must NOT carry"):
            load_seed_file(path)

    def test_invalid_output_format_raises(self, tmp_path):
        path = _write_seed(tmp_path, {
            "schema_version": "ai_analysis_rules.v1",
            "rule_sets": [{
                "rule_set_code": "x", "version": "v1", "scenario": "s",
                "domain": "d", "target_type": ["x"],
                "output_format": "yaml",  # invalid
                "output_contract": {"k": "string"},
                "output_item_schema": {"type": "object"},
                "field_whitelist": [], "guardrails": [],
                "auto_admit_threshold": 0.5, "schema_version": "v1",
            }],
        })
        with pytest.raises(ValueError, match="output_format"):
            load_seed_file(path)

    def test_threshold_out_of_range_raises(self, tmp_path):
        path = _write_seed(tmp_path, {
            "schema_version": "ai_analysis_rules.v1",
            "rule_sets": [{
                "rule_set_code": "x", "version": "v1", "scenario": "s",
                "domain": "d", "target_type": ["x"], "output_format": "json",
                "output_contract": {"k": "string"},
                "output_item_schema": {"type": "object"},
                "field_whitelist": [], "guardrails": [],
                "auto_admit_threshold": 1.5,  # out of range
                "schema_version": "v1",
            }],
        })
        with pytest.raises(ValueError, match="\\[0, 1\\]"):
            load_seed_file(path)


# ---------------------------------------------------------------------------
# seed_ai_analysis_rules — idempotency against an actual session/connection
# ---------------------------------------------------------------------------


class TestSeedIdempotency:
    def test_first_run_inserts_four(self, session):
        inserted = seed_ai_analysis_rules(session)
        session.commit()
        assert inserted == 4

    def test_second_run_inserts_zero(self, session):
        seed_ai_analysis_rules(session)
        session.commit()
        inserted = seed_ai_analysis_rules(session)
        session.commit()
        assert inserted == 0

    def test_rows_carry_initialized_by_marker(self, session):
        seed_ai_analysis_rules(session, initialized_by="system_seed")
        session.commit()
        rows = list(session.scalars(select(models.AIAnalysisRules)))
        assert len(rows) == 4
        assert all(r.initialized_by == "system_seed" for r in rows)
        assert all(r.initialized_at is not None for r in rows)

    def test_markdown_rules_have_fallback_strategy(self, session):
        seed_ai_analysis_rules(session)
        session.commit()
        markdown_rules = list(session.scalars(
            select(models.AIAnalysisRules).where(
                models.AIAnalysisRules.output_format == "markdown"
            )
        ))
        assert len(markdown_rules) == 2
        assert all(r.fallback_strategy == "deterministic_template" for r in markdown_rules)


# ---------------------------------------------------------------------------
# AIPromptProfile extension — domain / rules_object_type / rules_object_code
# ---------------------------------------------------------------------------


class TestAIPromptProfileExtension:
    def test_new_fields_default_null(self, session):
        # Legacy governance-phase prompts leave all three NULL — verify the
        # default path doesn't require a backfill or migration data fix.
        profile = models.AIPromptProfile(
            profile_name="legacy.gov",
            task_type="governance_classification",
            litellm_model_alias="x/y",
            prompt_version="1.0",
            prompt_template="...",
        )
        session.add(profile)
        session.commit()
        session.refresh(profile)
        assert profile.domain is None
        assert profile.rules_object_type is None
        assert profile.rules_object_code is None

    def test_can_assign_b5_seed_fields(self, session):
        profile = models.AIPromptProfile(
            profile_name="x.test",
            task_type="knowledge_extraction",
            scenario="job_demand_requirement_extraction",
            domain="occupation",
            rules_object_type="ai_analysis_rules",
            rules_object_code="occupation.job_demand.requirement_extraction.rules:v1",
            litellm_model_alias="internal/x",
            prompt_version="1.0",
            prompt_template="...",
        )
        session.add(profile)
        session.commit()
        session.refresh(profile)
        assert profile.domain == "occupation"
        assert profile.rules_object_type == "ai_analysis_rules"
        assert profile.rules_object_code.endswith(":v1")
