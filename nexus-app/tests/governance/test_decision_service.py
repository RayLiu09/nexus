"""Tests for GovernanceDecisionService — decision trail and status determination."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry
from nexus_app.enums import AIGovernanceRunAdoptionStatus, GovernanceResultStatus
from nexus_app.governance.decision_service import (
    GovernanceDecisionError,
    GovernanceDecisionService,
)


@pytest.fixture
def rules_registry() -> GovernanceRulesRegistry:
    rules = {
        "schema_version": "1.0",
        "classifications": [
            {"code": "D1", "name": "Domain 1", "description": "d", "criteria": ["c"]},
            {"code": "D2", "name": "Domain 2", "description": "d", "criteria": ["c"]},
            {"code": "major_distribution", "name": "Major distribution", "description": "d", "criteria": ["c"]},
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
    registry = GovernanceRulesRegistry()
    registry.load_dict(rules)
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
    """Actionable uncertainty remains in the review queue."""

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

    def test_sub_half_classification_confidence_is_isolated(self, rules_registry):
        svc = GovernanceDecisionService(rules_registry)
        run = _make_ai_run(
            {
                "classification": "D1",
                "level": "L1",
                "tags": ["pii"],
                "org_scope": "all",
                "confidence": 0.49,
            },
            {"quality_score": 85.0, "quality_level": "pass", "confidence": 0.49},
        )

        result = svc.execute_governance(_make_session(), run)

        assert result.status == GovernanceResultStatus.DISABLED
        assert result.index_admission is False
        classification = next(
            entry for entry in result.decision_trail if entry["field_name"] == "classification"
        )
        assert classification["adoption_status"] == "rejected"
        assert "isolation threshold 0.50" in classification["review_reason"]
        assert run.adoption_status == AIGovernanceRunAdoptionStatus.REJECTED


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

    def test_quality_warning_triggers_review_and_blocks_index_admission(self, rules_registry):
        svc = GovernanceDecisionService(rules_registry)
        ai_output = {
            "classification": "D1",
            "level": "L1",
            "tags": ["pii"],
            "org_scope": "all",
            "confidence": 0.95,
        }
        quality_summary = {
            "quality_score": 69.0,
            "quality_level": "warning",
            "confidence": 0.95,
        }

        result = svc.execute_governance(
            _make_session(), _make_ai_run(ai_output, quality_summary)
        )

        assert result.status == GovernanceResultStatus.REVIEW_REQUIRED
        assert result.index_admission is False
        quality_entry = next(
            entry for entry in result.decision_trail if entry["field_name"] == "quality"
        )
        assert quality_entry["adoption_status"] == "review_required"
        assert "quality_level=warning" in quality_entry["review_reason"]


class TestMajorDistributionStructureAdmission:
    def _high_confidence_output(self) -> dict:
        return {
            "classification": "major_distribution",
            "level": "L1",
            "tags": [],
            "org_scope": "all",
            "confidence": 0.95,
        }

    def _passing_quality(self) -> dict:
        return {"quality_score": 85.0, "quality_level": "pass", "confidence": 0.95}

    def test_document_cannot_be_adopted_as_major_distribution(self, rules_registry):
        session = _make_session()
        session.get.return_value = SimpleNamespace(
            normalized_type="document", metadata_summary={}
        )

        result = GovernanceDecisionService(rules_registry).execute_governance(
            session, _make_ai_run(self._high_confidence_output(), self._passing_quality())
        )

        classification = next(
            entry for entry in result.decision_trail if entry["field_name"] == "classification"
        )
        assert result.classification is None
        assert result.status == GovernanceResultStatus.REVIEW_REQUIRED
        assert result.index_admission is False
        assert classification["adoption_status"] == "review_required"
        assert "major_distribution_structure_missing" in classification["review_reason"]
        assert classification["threshold_check"]["major_distribution_structure"] == {
            "admitted": False,
            "reason": "normalized_type_must_be_record",
            "actual_normalized_type": "document",
        }

    def test_subthreshold_document_still_clears_major_distribution(self, rules_registry):
        session = _make_session()
        session.get.return_value = SimpleNamespace(
            normalized_type="document", metadata_summary={}
        )
        ai_output = self._high_confidence_output() | {"confidence": 0.75}

        result = GovernanceDecisionService(rules_registry).execute_governance(
            session, _make_ai_run(ai_output, self._passing_quality())
        )

        classification = next(
            entry for entry in result.decision_trail if entry["field_name"] == "classification"
        )
        assert result.classification is None
        assert result.status == GovernanceResultStatus.REVIEW_REQUIRED
        assert "major_distribution_structure_missing" in classification["review_reason"]

    def test_complete_record_projection_can_retain_major_distribution(self, rules_registry):
        session = _make_session()
        session.get.return_value = SimpleNamespace(
            normalized_type="record",
            metadata_summary={"domain_profile": "major_distribution.v1"},
        )
        session.scalar.side_effect = ["dataset-001", "record-001"]

        result = GovernanceDecisionService(rules_registry).execute_governance(
            session, _make_ai_run(self._high_confidence_output(), self._passing_quality())
        )

        classification = next(
            entry for entry in result.decision_trail if entry["field_name"] == "classification"
        )
        assert result.classification == "major_distribution"
        assert result.status == GovernanceResultStatus.AVAILABLE
        assert classification["adoption_status"] == "auto_adopted"
        assert classification["threshold_check"]["major_distribution_structure"] == {
            "admitted": True,
            "dataset_id": "dataset-001",
            "record_id": "record-001",
        }


class TestFreeFormTags:
    def test_free_form_tag_values_do_not_trigger_review(self, rules_registry):
        svc = GovernanceDecisionService(rules_registry)
        ai_output = {
            "classification": "D1",
            "level": "L1",
            "tags": ["电子商务", "国际贸易"],
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
        tag_entry = next(e for e in result.decision_trail if e["field_name"] == "tags")
        assert tag_entry["adoption_status"] == "auto_adopted"
        assert tag_entry["final_value"] == ["电子商务", "国际贸易"]

    def test_multi_stage_tag_values_are_persisted_to_decision_trail(self, rules_registry):
        svc = GovernanceDecisionService(rules_registry)
        ai_output = {
            "classification": "D1",
            "level": "L1",
            "tags": [],
            "_stages": {
                "tagging": {
                    "tags": {
                        "professional_domain": [
                            {"value": "电子商务", "criteria": "跨境电商行业报告"},
                            {"value": "doubao-seed-2-0-lite-260215", "criteria": "模型别名"},
                        ],
                        "data_source_type": [
                            {"value": "文件上传", "criteria": "接入方式"},
                            {"value": "第三方行业研究机构", "criteria": "AMZ123 出品"},
                        ],
                    },
                    "_task_type": "tagging",
                    "_model_alias": "doubao-seed-2-0-lite-260215",
                },
            },
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

        tag_entry = next(e for e in result.decision_trail if e["field_name"] == "tags")
        assert result.tags == ["电子商务", "第三方行业研究机构"]
        assert tag_entry["ai_suggestion"] == ["电子商务", "第三方行业研究机构"]
        assert tag_entry["final_value"] == ["电子商务", "第三方行业研究机构"]
        assert tag_entry["threshold_check"] == {
            "confidence_threshold_auto_adopt": 0.8,
            "actual_confidence": 0.95,
            "tag_contract": "free_form_values_under_fixed_dimensions",
            "extracted_tag_count": 2,
        }


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
