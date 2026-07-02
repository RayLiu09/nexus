from __future__ import annotations

import json
from pathlib import Path

from nexus_app.ai_governance.default_prompts import DEFAULT_PROMPTS
from nexus_app.ai_governance.rules_config import GovernanceRulesConfig
from nexus_app.ai_governance.seed_data import parse_classifications


REPO_ROOT = Path(__file__).resolve().parents[3]
RULES_PATH = REPO_ROOT / "config" / "governance_rules_v2.json"
EXCEL_PATH = REPO_ROOT / "docs" / "ai-governance" / "20260605数据清单.xlsx"


def _find(items: list[dict], code: str) -> dict:
    return next(item for item in items if item.get("code") == code)


def test_excel_course_textbook_row_builds_stable_governance_contract():
    classifications = parse_classifications(EXCEL_PATH)
    textbook = _find(classifications, "course_textbook")

    assert textbook["name"] == "教材"
    assert textbook["parent_type"] == "课程资源"
    assert textbook["primary_knowledge_type"] == "textbook_kb"
    assert textbook["default_level"] == "L2"
    assert "教材" in "、".join(textbook["title_keywords"])
    assert "本书" in textbook["content_keywords"]
    assert "教材" in "\n".join(textbook["criteria"])

    weights = [dim["weight"] for dim in textbook["quality_dimensions"]]
    assert all(weight > 0 for weight in weights)
    assert sum(weights) == 1.0
    assert {dim["name"] for dim in textbook["quality_dimensions"]} == {
        "来源可靠性",
        "信息时效性",
        "内容完整性",
        "合规与可用性",
    }


def test_governance_rules_v2_contains_course_textbook_and_validates():
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    GovernanceRulesConfig.model_validate(rules)

    textbook = _find(rules["classifications"], "course_textbook")
    assert textbook["primary_knowledge_type"] == "textbook_kb"
    assert textbook["default_level"] == "L2"
    assert "教材" in "\n".join(textbook["criteria"])
    assert sum(dim["weight"] for dim in textbook["quality_dimensions"]) == 1.0

    textbook_kb = _find(rules["knowledge_types"], "textbook_kb")
    assert "course_textbook" in textbook_kb["applicable_classifications"]
    assert textbook_kb["chunking_mode"] == "nexus_semantic"
    assert textbook_kb["chunking_strategy"] == "semantic_repack"


def test_default_governance_prompts_stay_rule_driven_for_course_textbook():
    joined = "\n".join(
        item["prompt_template"] for item in DEFAULT_PROMPTS.values()
    )

    assert "{{RULES}}" in joined
    assert "program_profile" not in joined
    assert "course_textbook_classification_prompt" not in joined
