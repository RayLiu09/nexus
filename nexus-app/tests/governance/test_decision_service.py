"""Tests for GovernanceDecisionService — decision trail and status determination."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry
from nexus_app.enums import GovernanceResultStatus
from nexus_app.governance.decision_service import (
    GovernanceDecisionError,
    GovernanceDecisionService,
)


@pytest.fixture
def rules_registry(tmp_path: Path) -> GovernanceRulesRegistry:
    rules = {
        "schema_version": "1.0",
        "classifications": [
            {"code": "D1", "name": "Domain 1", "description": "d", "criteria": ["c"]},
            {"code": "D2", "name": "Domain 2", "description": "d", "criteria": ["c"]},
        ],
        "levels": [
            {"code": "L1", "name": "Public", "description": "d", "criteria": ["c"]},
            {"code": "L2", "name": "Internal", "description": "d", "criteria": ["c"]},
            {"code": "L3", "name": "Confidential", "description": "d",
             "criteria": ["c"], "requires_approval": True},
            {"code": "L4", "name": "Secret", "description": "d",
             "criteria": ["c"], "requires_approval": True},
        ],
        "tags": [
            {"code": "pii", "name": "PII", "description": "d", "criteria": ["c"]},
            {"code": "financial", "name": "Financial", "description": "d", "criteria": ["c"]},
        ],
        "quality_scoring": {
            "dimensions": [
                {"name": "completeness", "weight": 0.5, "description": "d",
                 "check_items": [{"name": "has_title", "description": "d", "severity": "blocking"}]},
                {"name": "accuracy", "weight": 0.5, "description": "d",
                 "check_items": [{"name": "has_content", "description": "d", "severity": "warning"}]},
            ],
            "thresholds": {"pass": 70, "warning": 50, "review_required_below": 50},
            "confidence_threshold_auto_adopt": 0.8,
        },
    }
    rules_path = tmp_path / "governance_rules.json"
    rules_path.write_text(json.dumps(rules), encoding="utf-8")
    registry = GovernanceRulesRegistry()
    registry.load(str(rules_path))
    return registry


def _make_ai_run(ai_output: dict, quality_summary: dict | None = None):
    """Create a mock AIGovernanceRun with given output."""
    run = MagicMock()
    run.id = "run-001"
    run.normalized_ref_id = "ref-001"
    run.ai_output = ai_output
    run.quality_summary = quality_summary
    return run


def _make_session(existing_result=None):
    """Create a mock session whose idempotency lookup returns `existing_result`."""
    session = MagicMock()
    session.scalars.return_value.first.return_value = existing_result
    return session


class TestHighConfidenceAutoAdopt:
    """High confidence + quality pass → available."""

    def test_all_pass_produces_available(self, rules_registry):
        svc = GovernanceDecisionService(rules_registry)
        ai_output = {
            "classification": "D1",
            "level": "L1",
            "tags": ["pii"],
            "org_scope": "all",
            "confidence": 0.95,
        }
        quality_summary = {
            "quality_score": 85.0,
            "quality_level": "pass",
            "confidence": 0.95,
        }
        run = _make_ai_run(ai_output, quality_summary)
        session = _make_session()

        result = svc.execute_governance(session, run)

        assert result.status == GovernanceResultStatus.AVAILABLE
        assert result.rules_schema_version == "1.0"
        assert result.rules_content_hash is not None
        trail = result.decision_trail
        assert len(trail) == 4
        assert all(e["adoption_status"] == "auto_adopted" for e in trail)


class TestLowConfidenceReviewRequired:
    """Low confidence → review_required."""

    def test_low_confidence_triggers_review(self, rules_registry):
        svc = GovernanceDecisionService(rules_registry)
        ai_output = {
            "classification": "D1",
            "level": "L1",
            "tags": ["pii"],
            "org_scope": "all",
            "confidence": 0.5,
        }
        quality_summary = {
            "quality_score": 85.0,
            "quality_level": "pass",
            "confidence": 0.5,
        }
        run = _make_ai_run(ai_output, quality_summary)
        session = _make_session()

        result = svc.execute_governance(session, run)

        assert result.status == GovernanceResultStatus.REVIEW_REQUIRED
        trail = result.decision_trail
        review_entries = [e for e in trail if e["adoption_status"] == "review_required"]
        assert len(review_entries) >= 1
        assert "confidence" in review_entries[0]["review_reason"]


class TestQualityFailReviewRequired:
    """Quality fail → review_required."""

    def test_quality_fail_triggers_review(self, rules_registry):
        svc = GovernanceDecisionService(rules_registry)
        ai_output = {
            "classification": "D1",
            "level": "L1",
            "tags": ["pii"],
            "org_scope": "all",
            "confidence": 0.95,
        }
        quality_summary = {
            "quality_score": 40.0,
            "quality_level": "fail",
            "confidence": 0.95,
        }
        run = _make_ai_run(ai_output, quality_summary)
        session = _make_session()

        result = svc.execute_governance(session, run)

        assert result.status == GovernanceResultStatus.REVIEW_REQUIRED
        quality_entry = next(
            e for e in result.decision_trail if e["field_name"] == "quality"
        )
        assert quality_entry["adoption_status"] == "review_required"
        assert "fail" in quality_entry["review_reason"]


class TestLevelRequiresApproval:
    """L3/L4 with requires_approval → review_required."""

    def test_l3_requires_approval(self, rules_registry):
        svc = GovernanceDecisionService(rules_registry)
        ai_output = {
            "classification": "D1",
            "level": "L3",
            "tags": [],
            "org_scope": "all",
            "confidence": 0.95,
        }
        quality_summary = {
            "quality_score": 85.0,
            "quality_level": "pass",
            "confidence": 0.95,
        }
        run = _make_ai_run(ai_output, quality_summary)
        session = _make_session()

        result = svc.execute_governance(session, run)

        assert result.status == GovernanceResultStatus.REVIEW_REQUIRED
        level_entry = next(
            e for e in result.decision_trail if e["field_name"] == "level"
        )
        assert level_entry["adoption_status"] == "review_required"
        assert "requires_approval" in level_entry["review_reason"]


class TestIdempotency:
    """Re-invoking execute_governance for the same (ref, run) returns existing result."""

    def test_returns_existing_result(self, rules_registry):
        svc = GovernanceDecisionService(rules_registry)
        ai_output = {
            "classification": "D1", "level": "L1", "tags": [],
            "org_scope": "all", "confidence": 0.95,
        }
        quality_summary = {"quality_score": 85.0, "quality_level": "pass", "confidence": 0.95}
        run = _make_ai_run(ai_output, quality_summary)

        sentinel = MagicMock()
        sentinel.id = "existing-result-001"
        session = _make_session(existing_result=sentinel)

        result = svc.execute_governance(session, run)

        assert result is sentinel
        session.add.assert_not_called()


class TestNoAiOutput:
    """Missing ai_output raises GovernanceDecisionError."""

    def test_raises_on_missing_output(self, rules_registry):
        svc = GovernanceDecisionService(rules_registry)
        run = _make_ai_run(None)
        run.ai_output = None
        session = _make_session()

        with pytest.raises(GovernanceDecisionError):
            svc.execute_governance(session, run)
