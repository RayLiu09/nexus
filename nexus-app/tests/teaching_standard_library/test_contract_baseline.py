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


def test_persisted_course_contract_has_exactly_18_course_owned_fields() -> None:
    fields = _corpus()["course_business_fields"]

    assert len(fields) == 18
    assert len(set(fields)) == 18
    assert {
        "major_code",
        "major_name",
        "education_level",
        "confidence_level",
        "need_confirm",
        "review_status",
    }.isdisjoint(fields)


def test_contract_corpus_freezes_new_required_edge_cases() -> None:
    cases = {case["name"]: case for case in _corpus()["cases"]}

    undergraduate = cases["vocational_undergraduate_hour_rules"]
    assert undergraduate["hour_rules"]["total_hours_min"] == 3200
    assert undergraduate["hour_rules"]["practice_ratio_min"] == 0.6
    assert undergraduate["expected"]["initial_library_status"] == "review"

    same_name = cases["same_name_source_evidence_is_merged"]
    assert same_name["expected"]["retained_course_count"] == 1
    assert same_name["expected"]["retained_evidence_count"] == 2
    assert same_name["expected"]["unique_key"] == [
        "library_id",
        "course_type",
        "standard_course_name",
    ]
    assert same_name["expected"]["noise_discarded"] is False
    assert len({row["source_block_id"] for row in same_name["source_rows"]}) == 2

    named_training = cases["professional_course_name_is_not_blacklisted"]
    assert named_training["source_section"] == "专业拓展课程"
    assert named_training["expected"]["retained"] is True
    assert named_training["expected"]["name_blacklist_applied"] is False

    no_tool = cases["core_course_without_explicit_tool"]
    assert no_tool["expected"]["tool_tags"] == ["无特定工具要求"]
    assert no_tool["expected"]["initial_library_status"] == "review"
