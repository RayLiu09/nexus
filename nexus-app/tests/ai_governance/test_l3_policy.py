"""Tests for L3/L4 redaction policy + approved_private_model_aliases gate."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus_app.ai_governance.input_builder import (
    DefaultAIInputBuilder,
    RedactionPolicyError,
)
from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry


@pytest.fixture
def registry_with_approved(tmp_path: Path):
    rules = {
        "schema_version": "1.0",
        "classifications": [
            {"code": "D1", "name": "X", "description": "d", "criteria": ["c"]},
        ],
        "levels": [
            {"code": "L1", "name": "Public", "description": "d", "criteria": ["c"]},
            {"code": "L2", "name": "Internal", "description": "d", "criteria": ["c"]},
            {"code": "L3", "name": "Conf", "description": "d", "criteria": ["c"],
             "requires_approval": True, "forbid_external_llm": True},
            {"code": "L4", "name": "Secret", "description": "d", "criteria": ["c"],
             "requires_approval": True, "forbid_external_llm": True},
        ],
        "tags": [],
        "quality_scoring": {
            "dimensions": [{"name": "completeness", "weight": 1.0, "description": "d",
                            "check_items": [{"name": "h", "description": "d", "severity": "info"}]}],
            "thresholds": {"pass": 80, "warning": 60, "review_required_below": 50},
            "confidence_threshold_auto_adopt": 0.85,
        },
        "manual_review_triggers": [],
        "approved_private_model_aliases": ["nexus-private-l3-gpt"],
    }
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(rules))
    reg = GovernanceRulesRegistry()
    reg.load(str(path))
    return reg


class TestLevelPolicyEnforcement:
    def setup_method(self):
        self.builder = DefaultAIInputBuilder()
        self.ref = {"title": "t", "summary": "s", "content_snippet": "c"}

    def test_l1_any_policy_allowed(self, registry_with_approved):
        for policy in ("metadata_only", "masked_content", "full_content_private"):
            self.builder.build(self.ref, policy, "L1", registry=registry_with_approved)

    def test_l3_metadata_only_allowed(self, registry_with_approved):
        out = self.builder.build(self.ref, "metadata_only", "L3", registry=registry_with_approved)
        assert "[METADATA_ONLY" in out["payload"].get("content_snippet", "")

    def test_l3_masked_content_allowed(self, registry_with_approved):
        out = self.builder.build(self.ref, "masked_content", "L3", registry=registry_with_approved)
        assert "[MASKED" in out["payload"].get("content_snippet", "")

    def test_l3_full_content_private_with_approved_alias_allowed(self, registry_with_approved):
        out = self.builder.build(
            self.ref, "full_content_private", "L3",
            registry=registry_with_approved,
            model_alias="nexus-private-l3-gpt",
        )
        # full content survives the strategy
        assert out["payload"].get("content_snippet") == "c"

    def test_l3_full_content_private_with_unapproved_alias_rejected(self, registry_with_approved):
        with pytest.raises(RedactionPolicyError, match="approved_private_model_aliases"):
            self.builder.build(
                self.ref, "full_content_private", "L3",
                registry=registry_with_approved,
                model_alias="openai-gpt-4",  # not in approved list
            )

    def test_l4_full_content_private_with_no_alias_rejected(self, registry_with_approved):
        with pytest.raises(RedactionPolicyError):
            self.builder.build(
                self.ref, "full_content_private", "L4",
                registry=registry_with_approved,
                model_alias=None,
            )

    def test_unknown_policy_rejected(self, registry_with_approved):
        with pytest.raises(RedactionPolicyError, match="Unknown redaction_policy"):
            self.builder.build(self.ref, "unknown_policy_x", "L2", registry=registry_with_approved)
