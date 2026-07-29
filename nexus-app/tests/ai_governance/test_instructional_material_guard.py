from __future__ import annotations

from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry
from nexus_app.ai_governance.services import AIGovernanceService


def _registry() -> GovernanceRulesRegistry:
    registry = GovernanceRulesRegistry()
    registry.load_dict({
        "schema_version": "test",
        "classifications": [
            {"code": "course_textbook", "name": "课程资源教材", "criteria": []},
            {"code": "sector_report", "name": "行业报告", "criteria": []},
        ],
        "levels": [{"code": "L1", "name": "公开", "description": "", "criteria": []}],
        "tags": [], "knowledge_types": [],
        "quality_scoring": {
            "dimensions": [{"name": "completeness", "weight": 1.0, "description": "", "check_items": []}],
            "thresholds": {"pass": 80, "warning": 60, "review_required_below": 50},
            "confidence_threshold_auto_adopt": 0.85,
        },
        "manual_review_triggers": [],
        "approved_private_model_aliases": [],
    })
    return registry


def test_teaching_structure_overrides_topic_only_sector_report():
    output = {"classification_code": "sector_report", "confidence": 0.9}
    AIGovernanceService._apply_instructional_material_guard(
        output,
        {"title": "现代零售行业的关键特征", "content_snippet": "同学们好，欢迎来到微课堂。本节课讲解知识点，并布置课后作业。"},
        _registry(),
    )
    assert output["classification_code"] == "course_textbook"
    assert output["_rule_guardrail"]["original_model_output"]["classification_code"] == "sector_report"


def test_report_evidence_prevents_teaching_structure_override():
    output = {"classification_code": "sector_report", "confidence": 0.9}
    AIGovernanceService._apply_instructional_material_guard(
        output,
        {"content_snippet": "微课堂，本节课有知识点。发布单位为研究机构，报告年份2026，统计口径明确，市场规模持续增长。"},
        _registry(),
    )
    assert output["classification_code"] == "sector_report"
