"""Slice 0 contract baseline for the teaching-standard course library."""
from __future__ import annotations

import json
from pathlib import Path


_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "teaching_standard_course_library"
    / "slice0_contract_corpus.json"
)


def _corpus() -> dict:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def test_course_business_contract_has_exactly_21_fields() -> None:
    fields = _corpus()["course_business_fields"]

    assert len(fields) == 21
    assert len(set(fields)) == 21
    assert {"confidence_level", "need_confirm", "review_status"}.isdisjoint(fields)


def test_contract_corpus_freezes_new_required_edge_cases() -> None:
    cases = {case["name"]: case for case in _corpus()["cases"]}

    undergraduate = cases["vocational_undergraduate_hour_rules"]
    assert undergraduate["hour_rules"]["total_hours_min"] == 3200
    assert undergraduate["hour_rules"]["practice_ratio_min"] == 0.6
    assert undergraduate["expected"]["initial_library_status"] == "review"

    duplicate = cases["duplicate_core_course"]
    assert duplicate["expected"]["retained_course_count"] == 1
    assert duplicate["expected"]["diagnostic"] == "course_duplicate"
    assert all(row["course_field"] == "课程涉及的主要领域" for row in duplicate["core_rows"])
    assert duplicate["expected"]["standard_course_name"] == "市场策划"

    no_tool = cases["core_course_without_explicit_tool"]
    assert no_tool["expected"]["tool_tags"] == ["无特定工具要求"]
    assert no_tool["expected"]["initial_library_status"] == "review"
