"""Tests for knowledge_emissions — DETERMINISTIC rule lookup (§12 / §13).

Per docs/document_normalize_defects.md §12, knowledge type inference is no
longer AI-driven. It reads ``classification.primary_knowledge_type`` from
the active governance rules. The AI run only contributes ``classification``;
``ai_output.knowledge_type`` is ignored and the D2/D3/D4 fallback
heuristics have been deleted.

This fixture exercises the new contract with synthetic rules.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus_app.ai_governance.knowledge_type_inference import (
    _evaluate_co_emission_condition,
    infer_knowledge_emissions,
)
from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry


@pytest.fixture
def registry_with_textbook(tmp_path: Path):
    """Rules with classification ``D4`` mapped to KT ``course_textbook`` via
    ``primary_knowledge_type``. Mirrors the v2.1 schema shape."""
    rules = {
        "schema_version": "1.0",
        "classifications": [
            {
                "code": "D4",
                "name": "Teaching",
                "description": "d",
                "criteria": ["c"],
                "primary_knowledge_type": "course_textbook",
                "default_level": "L1",
                "co_emission_rules": [],
            },
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
                "code": "course_textbook",
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
    def test_primary_kt_resolved_by_rule_lookup(self, registry_with_textbook):
        """classification.primary_knowledge_type → primary emission. No AI hint needed."""
        ai_output = {"classification": "D4", "level": "L1", "confidence": 0.91}
        ref_dict = {"content_type": "document", "summary": ""}
        emissions = infer_knowledge_emissions(ai_output, ref_dict, registry_with_textbook)
        assert emissions
        primary = emissions[0]
        assert primary["code"] == "course_textbook"
        assert primary["primary"] is True
        assert primary["source"] == "rule_lookup"
        assert primary["confidence"] == pytest.approx(0.91)

    def test_ai_knowledge_type_field_is_ignored(self, registry_with_textbook):
        """Even when AI volunteers a knowledge_type, the rule lookup wins.
        Single source of truth = active rules (§12 deterministic contract)."""
        ai_output = {
            "classification": "D4",
            "level": "L1",
            "knowledge_type": "qa_corpus",   # AI tries to suggest a different KT
            "confidence": 0.9,
        }
        ref_dict = {"content_type": "document", "summary": ""}
        emissions = infer_knowledge_emissions(ai_output, ref_dict, registry_with_textbook)
        assert emissions
        assert emissions[0]["code"] == "course_textbook"  # rules win

    def test_missing_classification_returns_empty(self, registry_with_textbook):
        emissions = infer_knowledge_emissions({}, {}, registry_with_textbook)
        assert emissions == []

    def test_classification_not_in_rules_returns_empty(self, registry_with_textbook):
        ai_output = {"classification": "UNKNOWN_CODE", "confidence": 0.9}
        emissions = infer_knowledge_emissions(ai_output, {}, registry_with_textbook)
        assert emissions == []

    def test_classification_without_primary_kt_returns_empty(self, tmp_path):
        """When the rule file does not pin a primary_knowledge_type, no
        emission is produced (no silent AI fallback)."""
        rules = {
            "schema_version": "1.0",
            "classifications": [{"code": "D4", "name": "T", "description": "d",
                                 "criteria": ["c"]}],   # no primary_knowledge_type
            "levels": [{"code": code, "name": code, "description": "d",
                        "criteria": ["c"]} for code in ("L1", "L2", "L3", "L4")],
            "tags": [],
            "quality_scoring": {
                "dimensions": [{"name": "x", "weight": 1.0, "description": "d",
                                "check_items": [{"name": "h", "description": "d",
                                                 "severity": "info"}]}],
                "thresholds": {"pass": 80, "warning": 60, "review_required_below": 50},
                "confidence_threshold_auto_adopt": 0.85,
            },
            "manual_review_triggers": [],
            "knowledge_types": [],
        }
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(rules))
        reg = GovernanceRulesRegistry()
        reg.load(str(path))
        emissions = infer_knowledge_emissions({"classification": "D4"}, {}, reg)
        assert emissions == []

    def test_registry_exposes_knowledge_types(self, registry_with_textbook):
        kts = registry_with_textbook.get_knowledge_types()
        codes = {kt["code"] for kt in kts}
        assert "course_textbook" in codes
        assert registry_with_textbook.get_knowledge_type("course_textbook") is not None
        assert registry_with_textbook.get_knowledge_type("nonexistent") is None

    def test_ai_output_schema_still_accepts_optional_knowledge_type(self):
        """AI schema still HAS the field for back-compat; just not consumed."""
        from nexus_app.ai_governance.output_validator import AIGovernanceOutput
        out = AIGovernanceOutput(
            classification="D4", level="L1", overall_score=85.0, confidence=0.9,
            knowledge_type="course_textbook",
        )
        assert out.knowledge_type == "course_textbook"
        out2 = AIGovernanceOutput(
            classification="D4", level="L1", overall_score=85.0, confidence=0.9,
        )
        assert out2.knowledge_type is None

    def test_course_textbook_uses_course_textbook(self, tmp_path):
        rules = {
            "schema_version": "2.1",
            "classifications": [
                {
                    "code": "course_textbook",
                    "name": "教材",
                    "description": "课程资源教材",
                    "criteria": ["标题/封面关键词：教材"],
                    "primary_knowledge_type": "course_textbook",
                    "default_level": "L2",
                    "co_emission_rules": [],
                },
            ],
            "levels": [
                {"code": code, "name": code, "description": "d", "criteria": ["c"]}
                for code in ("L1", "L2", "L3", "L4")
            ],
            "tags": [],
            "quality_scoring": {
                "dimensions": [
                    {
                        "name": "x",
                        "weight": 1.0,
                        "description": "d",
                        "check_items": [
                            {"name": "h", "description": "d", "severity": "info"}
                        ],
                    }
                ],
                "thresholds": {"pass": 80, "warning": 60, "review_required_below": 50},
                "confidence_threshold_auto_adopt": 0.85,
            },
            "manual_review_triggers": [],
            "knowledge_types": [
                {
                    "code": "course_textbook",
                    "name": "教材知识库",
                    "applicable_classifications": ["course_textbook"],
                    "chunking_mode": "nexus_semantic",
                    "chunking_strategy": "semantic_repack",
                    "chunk_type": "semantic",
                    "co_emission_rules": [],
                }
            ],
        }
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(rules), encoding="utf-8")
        reg = GovernanceRulesRegistry()
        reg.load(str(path))

        emissions = infer_knowledge_emissions(
            {"classification": "course_textbook", "confidence": 0.93},
            {"content_type": "document"},
            reg,
        )

        assert emissions == [
            {
                "code": "course_textbook",
                "name": "教材知识库",
                "primary": True,
                "confidence": 0.93,
                "source": "rule_lookup",
                "evidence": [
                    "classification=course_textbook → primary_knowledge_type=course_textbook "
                    "(active rules)"
                ],
                "co_emission_origin": None,
            }
        ]


class TestCoEmission:
    def test_teaching_standard_structure_is_relation_bearing_evidence(self):
        score = _evaluate_co_emission_condition(
            "contains_concept_relations",
            {},
            {
                "content_snippet": (
                    "职业面向跨境电商运营岗位，培养规格包含语言能力、"
                    "数字营销能力，课程设置覆盖实训课程。"
                ),
                "summary": "",
            },
        )

        assert score == pytest.approx(0.75)

    def test_classification_side_co_emission_triggers(self, tmp_path):
        """co_emission_rules live on classification (§12). Triggers when
        the condition evaluates ≥ min_confidence against the AI run."""
        rules = {
            "schema_version": "1.0",
            "classifications": [
                {
                    "code": "competency_analysis",
                    "name": "职业能力分析表",
                    "description": "d",
                    "criteria": ["c"],
                    "primary_knowledge_type": "competency_graph",
                    "co_emission_rules": [
                        {"target_code": "skill_tag_library",
                         "condition": "contains_skill_taxonomy",
                         "min_confidence": 0.6},
                    ],
                },
            ],
            "levels": [{"code": code, "name": code, "description": "d",
                        "criteria": ["c"]} for code in ("L1", "L2", "L3", "L4")],
            "tags": [],
            "quality_scoring": {
                "dimensions": [{"name": "x", "weight": 1.0, "description": "d",
                                "check_items": [{"name": "h", "description": "d",
                                                 "severity": "info"}]}],
                "thresholds": {"pass": 80, "warning": 60, "review_required_below": 50},
                "confidence_threshold_auto_adopt": 0.85,
            },
            "manual_review_triggers": [],
            "knowledge_types": [
                {"code": "competency_graph", "name": "能力图谱",
                 "applicable_classifications": ["competency_analysis"],
                 "chunking_mode": "passthrough_to_ragflow",
                 "chunking_strategy": "graph_extract", "chunk_type": "graph",
                 "co_emission_rules": []},
                {"code": "skill_tag_library", "name": "技能标签库",
                 "applicable_classifications": [],
                 "chunking_mode": "passthrough_to_ragflow",
                 "chunking_strategy": "tag_decompose", "chunk_type": "structured",
                 "co_emission_rules": []},
            ],
        }
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(rules))
        reg = GovernanceRulesRegistry()
        reg.load(str(path))

        ai_output = {"classification": "competency_analysis", "confidence": 0.9}
        # ref_dict carries content_snippet with the keyword that triggers
        # contains_skill_taxonomy (≥ min_confidence 0.6).
        ref_dict = {"content_snippet": "本表列出岗位的技能点和技能要求…", "summary": ""}
        emissions = infer_knowledge_emissions(ai_output, ref_dict, reg)
        assert {e["code"] for e in emissions} == {"competency_graph", "skill_tag_library"}
        primary = next(e for e in emissions if e["primary"])
        assert primary["code"] == "competency_graph"
        co = next(e for e in emissions if not e["primary"])
        assert co["code"] == "skill_tag_library"
        assert co["co_emission_origin"] == "competency_graph"
        assert co["source"] == "co_emission_rule"

    def test_classification_co_emission_skipped_when_condition_weak(self, tmp_path):
        rules = {
            "schema_version": "1.0",
            "classifications": [
                {
                    "code": "competency_analysis",
                    "name": "n",
                    "description": "d",
                    "criteria": ["c"],
                    "primary_knowledge_type": "competency_graph",
                    "co_emission_rules": [
                        {"target_code": "skill_tag_library",
                         "condition": "contains_skill_taxonomy",
                         "min_confidence": 0.6},
                    ],
                },
            ],
            "levels": [{"code": code, "name": code, "description": "d",
                        "criteria": ["c"]} for code in ("L1", "L2", "L3", "L4")],
            "tags": [],
            "quality_scoring": {
                "dimensions": [{"name": "x", "weight": 1.0, "description": "d",
                                "check_items": [{"name": "h", "description": "d",
                                                 "severity": "info"}]}],
                "thresholds": {"pass": 80, "warning": 60, "review_required_below": 50},
                "confidence_threshold_auto_adopt": 0.85,
            },
            "manual_review_triggers": [],
            "knowledge_types": [
                {"code": "competency_graph", "name": "n",
                 "chunking_mode": "passthrough_to_ragflow",
                 "chunking_strategy": "graph_extract", "chunk_type": "graph",
                 "co_emission_rules": []},
                {"code": "skill_tag_library", "name": "n",
                 "chunking_mode": "passthrough_to_ragflow",
                 "chunking_strategy": "tag_decompose", "chunk_type": "structured",
                 "co_emission_rules": []},
            ],
        }
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(rules))
        reg = GovernanceRulesRegistry()
        reg.load(str(path))

        ai_output = {"classification": "competency_analysis", "confidence": 0.9}
        # ref_dict has no skill-taxonomy keywords → condition returns 0.3 < 0.6.
        ref_dict = {"content_snippet": "本表是某项数据的统计结果。", "summary": ""}
        emissions = infer_knowledge_emissions(ai_output, ref_dict, reg)
        assert [e["code"] for e in emissions] == ["competency_graph"]
