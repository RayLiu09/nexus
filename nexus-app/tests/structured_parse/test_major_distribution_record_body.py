from __future__ import annotations

from pathlib import Path

import pytest

from nexus_app.profile_detect import detect
from nexus_app.structured_parse import parse_xlsx
from nexus_app.structured_parse.record_body_adapter import project_to_record_body

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_MAJOR_MULTI = REPO_ROOT / "docs/samples/2.（专业布点数）专业布点数.xlsx"
SAMPLE_MAJOR_ECOMMERCE = REPO_ROOT / "docs/samples/电子商务专业布点数量.xlsx"


def _record_body(path: Path) -> dict:
    wb = parse_xlsx(path.read_bytes(), source_filename=path.name)
    profile = detect(wb).model_dump(exclude_none=True)
    return project_to_record_body(wb.model_dump(), profile)


@pytest.mark.skipif(not SAMPLE_MAJOR_MULTI.exists(), reason="sample missing")
def test_major_distribution_multi_sample_projection() -> None:
    body = _record_body(SAMPLE_MAJOR_MULTI)

    assert body["dataset"]["record_count"] == 2
    assert body["dataset"]["placeholder_count"] == 1
    assert body["dataset"]["ignored_summary_count"] == 0
    assert body["dataset"]["major_scope"] == "multi_major"
    assert [r["major_code"] for r in body["records"]] == ["530704", "530702"]
    assert {r["education_level"] for r in body["records"]} == {"高职"}


@pytest.mark.skipif(not SAMPLE_MAJOR_ECOMMERCE.exists(), reason="sample missing")
def test_major_distribution_ecommerce_sample_projection_ignores_summary() -> None:
    body = _record_body(SAMPLE_MAJOR_ECOMMERCE)

    assert body["dataset"]["record_count"] == 32
    assert body["dataset"]["ignored_summary_count"] == 1
    assert body["dataset"]["major_scope"] == "single_major"
    assert body["dataset"]["major_name"] == "电子商务"
    assert body["dataset"]["major_code"] == "530701"
    assert body["field_inference"]["education_level"]["filled"] is False
    assert all(r["province_name"] != "全部" for r in body["records"])
    assert body["records"][0]["province_name"] == "北京市"
    assert body["records"][0]["distribution_count"] == 19
    assert body["records"][-1]["province_name"] == "新疆生产建设兵团"
    assert body["records"][-1]["region_scope"] == "province"
