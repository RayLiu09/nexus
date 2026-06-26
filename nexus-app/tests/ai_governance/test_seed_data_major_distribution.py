from __future__ import annotations

import json
from pathlib import Path

from nexus_app.ai_governance.seed_data import _build_code


def test_major_distribution_seed_code() -> None:
    assert _build_code("专业布点数") == "major_distribution"


def test_governance_rules_v2_uses_major_distribution_code() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    rules_path = repo_root / "config" / "governance_rules_v2.json"
    rules = json.loads(rules_path.read_text())

    classification_codes = {item["code"] for item in rules["classifications"]}
    assert "major_distribution" in classification_codes
    assert "program_distribution" not in classification_codes

    for knowledge_type in rules.get("knowledge_types", []):
        applicable = knowledge_type.get("applicable_classifications", [])
        assert "program_distribution" not in applicable
