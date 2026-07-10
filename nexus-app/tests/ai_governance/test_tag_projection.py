"""PR-6 projection engine guards (v1.3 §2.4).

The engine is deterministic and side-effect free at the ``project_*``
layer; ``persist_tag_rows`` is the only piece that touches the DB.
Tests cover both.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from nexus_app import models
from nexus_app.ai_governance.projection_config import PROJECTION_WHITELIST_V1_3
from nexus_app.ai_governance.tag_projection import (
    TagRowPayload,
    _TABLE_TO_TARGET_TYPE,
    persist_tag_rows,
    project_conditional_projections,
    project_field_projections,
    project_record_to_tag_rows,
)
from nexus_app.enums import TagAssetIndexSource, TagAssetIndexTargetType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def job_demand_record() -> dict:
    """Typical field-only Pipeline B row after B4 normalisation."""
    return {
        "city": "北京市",
        "industry_name": "直播电商",
        "job_title": "直播运营",
        "source_published_at": datetime(2025, 6, 1, tzinfo=timezone.utc),
        # local_only fields must not appear as tags
        "salary_min": 8000,
        "salary_max": 15000,
        "education_requirement": "本科",
        "company_name": "示例公司",
        # long-text field must never leak into topics
        "job_skill_text": "熟练掌握 GMV 拆解、投放 ROI 分析",
    }


@pytest.fixture
def major_distribution_record() -> dict:
    return {
        "province_name": "广东省",
        "major_name": "电子商务",
        "major_code": "610101",
        "year": 2024,
        # local_only
        "region_scope": "省级",
        "education_level": "高职",
        "distribution_count": 32,
    }


@pytest.fixture
def occupational_ability_row() -> dict:
    return {
        "ability_content": "GMV 拆解与投放 ROI 分析",
        # local_only internal sequence codes
        "ability_code": "PGSD-042",
        "ability_major_category_code": "A03",
        "ability_major_category_name": "数据分析",
        "ability_sequence": "42",
    }


# ---------------------------------------------------------------------------
# Coverage / mapping invariants
# ---------------------------------------------------------------------------


class TestMappingCoverage:
    def test_every_whitelist_table_maps_to_a_target_type(self) -> None:
        for table_name in PROJECTION_WHITELIST_V1_3:
            assert table_name in _TABLE_TO_TARGET_TYPE, (
                f"whitelist table {table_name!r} has no entry in "
                "_TABLE_TO_TARGET_TYPE — projection engine will refuse "
                "to run against it."
            )

    def test_unknown_table_raises(self) -> None:
        with pytest.raises(KeyError, match="no projection whitelist entry"):
            project_record_to_tag_rows(
                table_name="does_not_exist",
                record={},
                target_id="x",
                asset_version_id="y",
            )


# ---------------------------------------------------------------------------
# field_projections
# ---------------------------------------------------------------------------


class TestJobDemandFieldProjections:
    def test_produces_expected_four_dimensions(self, job_demand_record) -> None:
        payloads = project_record_to_tag_rows(
            table_name="job_demand_record",
            record=job_demand_record,
            target_id="jd-1",
            asset_version_id="ver-1",
        )
        by_type = {(p.tag_type, p.tag_value_normalized): p for p in payloads}
        assert ("region", "北京") in by_type
        assert ("industry", "直播电商") in by_type
        assert ("occupation", "直播运营") in by_type
        # time_range from datetime → year
        assert ("time_range", "2025") in by_type

    def test_local_only_fields_never_emitted(self, job_demand_record) -> None:
        payloads = project_record_to_tag_rows(
            table_name="job_demand_record",
            record=job_demand_record,
            target_id="jd-1",
            asset_version_id="ver-1",
        )
        emitted_values = {p.tag_value for p in payloads}
        for local_field in ("8000", "15000", "本科", "示例公司"):
            assert local_field not in emitted_values

    def test_long_text_field_never_emitted(self, job_demand_record) -> None:
        payloads = project_record_to_tag_rows(
            table_name="job_demand_record",
            record=job_demand_record,
            target_id="jd-1",
            asset_version_id="ver-1",
        )
        # Long text stays in chunk layer — no tag row for it.
        for p in payloads:
            assert "GMV 拆解" not in p.tag_value
            assert "投放" not in p.tag_value

    def test_null_field_skipped(self) -> None:
        """Missing city / industry_name / job_title should just skip."""
        payloads = project_record_to_tag_rows(
            table_name="job_demand_record",
            record={"city": None, "industry_name": "", "job_title": "   "},
            target_id="jd-1",
            asset_version_id="ver-1",
        )
        assert payloads == []

    def test_normalisation_applied_via_shared_function(self) -> None:
        """The engine must delegate to normalize_tag_value so drift between
        the projection path and the read path can't happen."""
        payloads = project_record_to_tag_rows(
            table_name="job_demand_record",
            record={
                "city": "  广东省  ",
                "industry_name": "直播电商（含短视频）",
            },
            target_id="jd-2",
            asset_version_id="ver-1",
        )
        by_type = {p.tag_type: p for p in payloads}
        # region suffix stripped
        assert by_type["region"].tag_value_normalized == "广东"
        assert by_type["region"].tag_value == "广东省"
        # bracket content stripped for industry
        assert by_type["industry"].tag_value_normalized == "直播电商"
        assert by_type["industry"].tag_value == "直播电商（含短视频）"

    def test_target_type_is_record_polymorphic(self, job_demand_record) -> None:
        payloads = project_record_to_tag_rows(
            table_name="job_demand_record",
            record=job_demand_record,
            target_id="jd-1",
            asset_version_id="ver-1",
        )
        for p in payloads:
            assert p.target_type == TagAssetIndexTargetType.JOB_DEMAND_RECORD

    def test_source_default_is_field_projection(self, job_demand_record) -> None:
        payloads = project_record_to_tag_rows(
            table_name="job_demand_record",
            record=job_demand_record,
            target_id="jd-1",
            asset_version_id="ver-1",
        )
        for p in payloads:
            assert p.source == TagAssetIndexSource.FIELD_PROJECTION
            # field projections carry no LLM confidence
            assert p.confidence is None
            assert p.extraction_run_id is None


class TestMajorDistribution:
    def test_five_projections(self, major_distribution_record) -> None:
        payloads = project_record_to_tag_rows(
            table_name="major_distribution_record",
            record=major_distribution_record,
            target_id="md-1",
            asset_version_id="ver-1",
        )
        by = {(p.tag_type, p.tag_value_normalized): p for p in payloads}
        assert ("region", "广东") in by
        assert ("major", "电子商务") in by
        assert ("major", "610101") in by  # major_code + major
        assert ("time_range", "2024") in by

    def test_region_scope_stays_local(self, major_distribution_record) -> None:
        """v1.3 R3 fix — region_scope stores operational bucket values,
        not real regions."""
        payloads = project_record_to_tag_rows(
            table_name="major_distribution_record",
            record=major_distribution_record,
            target_id="md-1",
            asset_version_id="ver-1",
        )
        for p in payloads:
            assert p.tag_value != "省级"

    def test_education_level_stays_local(self, major_distribution_record) -> None:
        payloads = project_record_to_tag_rows(
            table_name="major_distribution_record",
            record=major_distribution_record,
            target_id="md-1",
            asset_version_id="ver-1",
        )
        for p in payloads:
            assert p.tag_value != "高职"


class TestOccupationalAbility:
    def test_ability_content_only(self, occupational_ability_row) -> None:
        """v1.3 R2 fix — ability_content is the semantic anchor.  Internal
        sequence codes (ability_code / _major_category_code / _sequence)
        must never be projected because they are per-analysis-instance
        auto-generated codes with no cross-asset semantics."""
        payloads = project_record_to_tag_rows(
            table_name="occupational_ability_item",
            record=occupational_ability_row,
            target_id="oai-1",
            asset_version_id="ver-1",
        )
        assert len(payloads) == 1
        assert payloads[0].tag_type == "ability"
        assert payloads[0].tag_value == "GMV 拆解与投放 ROI 分析"
        # Internal codes never leak
        for p in payloads:
            assert p.tag_value != "PGSD-042"
            assert p.tag_value != "A03"


# ---------------------------------------------------------------------------
# conditional_projections
# ---------------------------------------------------------------------------


class TestRequirementItemConditional:
    def test_professional_skill_projected_to_ability_plus_topic(self) -> None:
        record = {
            "item_type": "professional_skill",
            "normalized_name": "GMV 拆解",
            "item_name": "GMV拆解能力",
        }
        payloads = project_record_to_tag_rows(
            table_name="job_demand_requirement_item",
            record=record,
            target_id="jdri-1",
            asset_version_id="ver-1",
        )
        tag_types = {p.tag_type for p in payloads}
        assert tag_types == {"ability", "topic"}
        # normalized_name preferred over item_name
        for p in payloads:
            assert p.tag_value == "GMV 拆解"

    def test_normalized_name_missing_falls_back_to_item_name(self) -> None:
        record = {
            "item_type": "professional_skill",
            "normalized_name": None,
            "item_name": "GMV 拆解",
        }
        payloads = project_record_to_tag_rows(
            table_name="job_demand_requirement_item",
            record=record,
            target_id="jdri-1",
            asset_version_id="ver-1",
        )
        assert len(payloads) == 2
        for p in payloads:
            assert p.tag_value == "GMV 拆解"

    def test_other_item_types_skipped(self) -> None:
        for skipped in ("tool", "certificate", "professional_literacy", "work_task_candidate"):
            record = {"item_type": skipped, "normalized_name": "x", "item_name": "y"}
            payloads = project_record_to_tag_rows(
                table_name="job_demand_requirement_item",
                record=record,
                target_id="jdri-1",
                asset_version_id="ver-1",
            )
            assert payloads == [], f"item_type={skipped!r} should be skipped"


# ---------------------------------------------------------------------------
# time_range handling
# ---------------------------------------------------------------------------


class TestTimeRangeExtraction:
    def test_int_year_extracted(self) -> None:
        payloads = project_field_projections(
            table_name="major_distribution_record",
            record={"year": 2024},
            target_type=TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
            target_id="md-1",
            asset_version_id="ver-1",
            source=TagAssetIndexSource.FIELD_PROJECTION,
        )
        time_ranges = [p for p in payloads if p.tag_type == "time_range"]
        assert len(time_ranges) == 1
        assert time_ranges[0].tag_value == "2024"
        assert time_ranges[0].tag_value_normalized == "2024"

    def test_datetime_extracts_year(self) -> None:
        payloads = project_field_projections(
            table_name="job_demand_record",
            record={"source_published_at": datetime(2026, 3, 15, tzinfo=timezone.utc)},
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            target_id="jd-1",
            asset_version_id="ver-1",
            source=TagAssetIndexSource.FIELD_PROJECTION,
        )
        time_ranges = [p for p in payloads if p.tag_type == "time_range"]
        assert len(time_ranges) == 1
        assert time_ranges[0].tag_value == "2026"

    def test_date_extracts_year(self) -> None:
        payloads = project_field_projections(
            table_name="job_demand_record",
            record={"source_published_at": date(2025, 12, 31)},
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            target_id="jd-1",
            asset_version_id="ver-1",
            source=TagAssetIndexSource.FIELD_PROJECTION,
        )
        time_ranges = [p for p in payloads if p.tag_type == "time_range"]
        assert len(time_ranges) == 1
        assert time_ranges[0].tag_value == "2025"

    def test_invalid_year_string_falls_back_to_freeform(self) -> None:
        payloads = project_field_projections(
            table_name="major_distribution_record",
            record={"year": "近三年"},
            target_type=TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
            target_id="md-1",
            asset_version_id="ver-1",
            source=TagAssetIndexSource.FIELD_PROJECTION,
        )
        time_ranges = [p for p in payloads if p.tag_type == "time_range"]
        # Fallback: preserved as free-form for L4 semantic match.
        assert len(time_ranges) == 1
        assert time_ranges[0].tag_value == "近三年"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_duplicate_normalised_value_across_rules_collapsed(self) -> None:
        """A record with identical values across `field_projections` and
        `conditional_projections` must yield deduplicated rows so
        persistence doesn't need to defend against dup keys."""
        record = {
            "item_type": "professional_skill",
            "normalized_name": "GMV 拆解",
            "item_name": "GMV 拆解",
        }
        payloads = project_record_to_tag_rows(
            table_name="job_demand_requirement_item",
            record=record,
            target_id="jdri-1",
            asset_version_id="ver-1",
        )
        # (ability, GMV拆解) + (topic, GMV拆解) — 2 rows, not 4.
        assert len(payloads) == 2


# ---------------------------------------------------------------------------
# I-10 idempotency at persistence layer
# ---------------------------------------------------------------------------


class TestPersistenceIdempotency:
    def test_persist_delete_then_insert(self, session, job_demand_record) -> None:
        payloads = project_record_to_tag_rows(
            table_name="job_demand_record",
            record=job_demand_record,
            target_id="jd-1",
            asset_version_id="ver-1",
        )
        inserted = persist_tag_rows(
            session, payloads,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            target_id="jd-1",
            source=TagAssetIndexSource.FIELD_PROJECTION,
        )
        assert inserted == len(payloads)

        rows = session.scalars(
            select(models.TagAssetIndex).where(
                models.TagAssetIndex.target_id == "jd-1"
            )
        ).all()
        assert len(rows) == len(payloads)

    def test_re_run_yields_same_row_count(self, session, job_demand_record) -> None:
        """I-10 invariant: same input → same output row count."""
        for _ in range(3):
            payloads = project_record_to_tag_rows(
                table_name="job_demand_record",
                record=job_demand_record,
                target_id="jd-1",
                asset_version_id="ver-1",
            )
            persist_tag_rows(
                session, payloads,
                target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
                target_id="jd-1",
                source=TagAssetIndexSource.FIELD_PROJECTION,
            )
        rows = session.scalars(
            select(models.TagAssetIndex).where(
                models.TagAssetIndex.target_id == "jd-1"
            )
        ).all()
        # 4 projections, no duplicates.
        assert len(rows) == 4

    def test_empty_payloads_still_wipes_previous(self, session, job_demand_record) -> None:
        """When a record loses all its taggable fields (all-null
        rewrite), the projection engine returns [] and persist_tag_rows
        must still clean up previous rows."""
        # First run — populate 4 tags.
        payloads = project_record_to_tag_rows(
            table_name="job_demand_record",
            record=job_demand_record,
            target_id="jd-1",
            asset_version_id="ver-1",
        )
        persist_tag_rows(
            session, payloads,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            target_id="jd-1",
            source=TagAssetIndexSource.FIELD_PROJECTION,
        )

        # Second run — record becomes all-null; engine yields [].
        empty_payloads = project_record_to_tag_rows(
            table_name="job_demand_record",
            record={"city": None, "industry_name": None, "job_title": None,
                    "source_published_at": None},
            target_id="jd-1",
            asset_version_id="ver-1",
        )
        assert empty_payloads == []
        persist_tag_rows(
            session, empty_payloads,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            target_id="jd-1",
            source=TagAssetIndexSource.FIELD_PROJECTION,
        )

        # Previous rows must be gone.
        rows = session.scalars(
            select(models.TagAssetIndex).where(
                models.TagAssetIndex.target_id == "jd-1"
            )
        ).all()
        assert rows == []

    def test_persist_does_not_touch_other_source_rows(
        self, session, job_demand_record,
    ) -> None:
        """A field_projection re-run must not delete governance_tag rows
        for the same target."""
        # Seed a governance_tag row.
        session.add(models.TagAssetIndex(
            tag_type="region",
            tag_value="北京市",
            tag_value_normalized="北京",
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            target_id="jd-1",
            asset_version_id="ver-1",
            source=TagAssetIndexSource.GOVERNANCE_TAG,
            confidence=0.94,
            extraction_run_id="run-1",
        ))
        session.flush()

        # Now run field projection.
        payloads = project_record_to_tag_rows(
            table_name="job_demand_record",
            record=job_demand_record,
            target_id="jd-1",
            asset_version_id="ver-1",
        )
        persist_tag_rows(
            session, payloads,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            target_id="jd-1",
            source=TagAssetIndexSource.FIELD_PROJECTION,
        )

        # Governance_tag row still present.
        gov = session.scalars(
            select(models.TagAssetIndex).where(
                models.TagAssetIndex.source == TagAssetIndexSource.GOVERNANCE_TAG,
                models.TagAssetIndex.target_id == "jd-1",
            )
        ).all()
        assert len(gov) == 1
