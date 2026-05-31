"""Tests for knowledge_emissions: schema-level AI output → infer_knowledge_emissions."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus_app.ai_governance.knowledge_type_inference import infer_knowledge_emissions
from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry


@pytest.fixture
def registry_with_textbook(tmp_path: Path):
    rules = {
        "schema_version": "1.0",
        "classifications": [
            {"code": "D4", "name": "Teaching", "description": "d", "criteria": ["c"]},
        ],
        "levels": [
            {"code": "L1", "name": "Public", "description": "d", "criteria": ["c"]},
            {"code": "L2", "name": "Internal", "description": "d", "criteria": ["c"]},
            {"code": "L3", "name": "Conf", "description": "d", "criteria": ["c"],
             "requires_approval": True},
            {"code": "L4", "name": "Secret", "description": "d", "criteria": ["c"],
             "requires_approval": True},
        ],
        "tags": [],
        "quality_scoring": {
            "dimensions": [{"name": "completeness", "weight": 1.0, "description": "d",
                            "check_items": [{"name": "h", "description": "d", "severity": "info"}]}],
            "thresholds": {"pass": 80, "warning": 60, "review_required_below": 50},
            "confidence_threshold_auto_adopt": 0.85,
        },
        "manual_review_triggers": [],
        "knowledge_types": [
            {
                "code": "textbook_kb",
                "name": "Textbook KB",
                "applicable_classifications": ["D4"],
                "chunking_mode": "passthrough_to_ragflow",
                "chunking_strategy": "semantic",
                "chunk_type": "semantic",
                "co_emission_rules": [],
            },
        ],
    }
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(rules))
    reg = GovernanceRulesRegistry()
    reg.load(str(path))
    return reg


class TestKnowledgeEmissions:
    def test_string_knowledge_type_consumed_directly(self, registry_with_textbook):
        ai_output = {
            "classification": "D4",
            "level": "L1",
            "knowledge_type": "textbook_kb",
            "confidence": 0.91,
        }
        ref_dict = {"content_type": "document", "summary": ""}
        emissions = infer_knowledge_emissions(ai_output, ref_dict, registry_with_textbook)
        assert emissions
        primary = emissions[0]
        assert primary["code"] == "textbook_kb"
        assert primary["primary"] is True
        assert primary["confidence"] == pytest.approx(0.91)

    def test_missing_knowledge_type_falls_back_to_heuristic(self, registry_with_textbook):
        ai_output = {"classification": "D4", "level": "L1", "confidence": 0.9}
        ref_dict = {"content_type": "教材课件", "summary": ""}
        emissions = infer_knowledge_emissions(ai_output, ref_dict, registry_with_textbook)
        assert emissions
        assert emissions[0]["code"] == "textbook_kb"

    def test_registry_exposes_knowledge_types(self, registry_with_textbook):
        kts = registry_with_textbook.get_knowledge_types()
        codes = {kt["code"] for kt in kts}
        assert "textbook_kb" in codes
        assert registry_with_textbook.get_knowledge_type("textbook_kb") is not None
        assert registry_with_textbook.get_knowledge_type("nonexistent") is None

    def test_ai_output_schema_accepts_optional_knowledge_type(self):
        from nexus_app.ai_governance.output_validator import AIGovernanceOutput
        out = AIGovernanceOutput(
            classification="D4", level="L1", overall_score=85.0, confidence=0.9,
            knowledge_type="textbook_kb",
        )
        assert out.knowledge_type == "textbook_kb"
        # also accepts None / omission
        out2 = AIGovernanceOutput(
            classification="D4", level="L1", overall_score=85.0, confidence=0.9,
        )
        assert out2.knowledge_type is None
