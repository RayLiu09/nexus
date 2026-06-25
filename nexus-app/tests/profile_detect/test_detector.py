"""Tests for the three `profile_detect` detectors + the main dispatcher.

Two layers:

  1. Synthetic ParsedWorkbook tests — fastest, lock individual scoring
     rules without depending on samples.
  2. Sample-file integration tests — exercise the full pipeline
     (parse_xlsx → detect) against `docs/samples/` to confirm the real
     workbooks land in the expected record_type / domain_profile /
     confidence band.

The detector layer is deliberately fail-safe: every input — including an
empty ParsedWorkbook — produces a ProfileDetectResult, never raises.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from nexus_app.profile_detect import (
    DEFAULT_AUTO_ADMIT_THRESHOLD,
    DETECTOR_VERSION,
    detect,
    detect_ability_analysis_pgsd,
    detect_generic_table,
    detect_job_demand,
)
from nexus_app.structured_parse import parse_xlsx
from nexus_app.structured_parse.schemas import (
    ParsedCell,
    ParsedRow,
    ParsedSheet,
    ParsedWorkbook,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_JOB_DEMAND = REPO_ROOT / "docs/samples/1.（岗位需求）电子商务岗位招聘数据.xlsx"
SAMPLE_ABILITY = REPO_ROOT / "docs/samples/2.（职业能力分析）大数据技术应用专业职业能力分析表.xlsx"


# ---------------------------------------------------------------------------
# ParsedWorkbook builders — keep tests readable without re-encoding xlsx bytes
# ---------------------------------------------------------------------------


def _cell(col: int, value, *, multiline: bool = False) -> ParsedCell:
    letter = chr(ord("A") + col - 1)
    return ParsedCell(
        column=col,
        column_letter=letter,
        value=value,
        is_multiline=multiline,
    )


def _row(row_index: int, values: list) -> ParsedRow:
    return ParsedRow(
        row_index=row_index,
        cells=[_cell(i, v) for i, v in enumerate(values, start=1)],
    )


def _sheet(
    name: str,
    *,
    sheet_index: int = 0,
    rows: list[ParsedRow] | None = None,
) -> ParsedSheet:
    rows = rows or []
    return ParsedSheet(
        name=name,
        sheet_index=sheet_index,
        rows=rows,
        column_count=max((len(r.cells) for r in rows), default=0),
        row_count=len(rows),
    )


def _workbook(sheets: list[ParsedSheet]) -> ParsedWorkbook:
    return ParsedWorkbook(
        parser_version="test_parser.v1",
        parsed_at=datetime(2026, 6, 25, tzinfo=timezone.utc),
        timezone="Asia/Shanghai",
        sheets=sheets,
    )


# ---------------------------------------------------------------------------
# Detector: generic_table fallback
# ---------------------------------------------------------------------------


class TestDetectGenericTable:
    def test_always_returns_low_confidence_generic_table(self):
        wb = _workbook([_sheet("Sheet1", rows=[_row(1, ["a", "b"])])])
        result = detect_generic_table(wb)
        assert result.record_type == "generic_table_dataset"
        assert result.domain_profile == "generic_table.v1"
        assert 0.0 < result.confidence < DEFAULT_AUTO_ADMIT_THRESHOLD
        assert result.evidence.sheet_names == ["Sheet1"]

    def test_empty_workbook_still_returns_result(self):
        # Detector must never raise — empty workbook is a valid input that
        # downstream tooling may receive from a corrupt / blank source.
        result = detect_generic_table(_workbook([]))
        assert result.record_type == "generic_table_dataset"
        assert result.confidence > 0
        assert result.evidence.sheet_names == []


# ---------------------------------------------------------------------------
# Detector: job_demand
# ---------------------------------------------------------------------------


class TestDetectJobDemandSynthetic:
    def test_full_recruiting_header_yields_high_confidence(self):
        # 3 required + 4 optional headers — should clear auto-admit threshold.
        wb = _workbook([
            _sheet("Sheet1", rows=[
                _row(1, ["岗位名称", "城市", "公司名称", "薪资", "学历要求", "岗位描述", "发布时间"]),
                _row(2, ["平面设计师", "上海", "ACME", "10k-15k", "本科", "...", "2025-01"]),
            ]),
        ])
        result = detect_job_demand(wb)
        assert result.record_type == "job_demand_dataset"
        assert result.domain_profile == "job_demand.v1"
        assert result.confidence >= DEFAULT_AUTO_ADMIT_THRESHOLD
        # evidence carries every matched header for the review queue
        for h in ["岗位名称", "城市", "公司名称", "薪资", "学历要求", "岗位描述", "发布时间"]:
            assert h in result.evidence.matched_headers
        # sample_row_count excludes header row
        assert result.evidence.sample_row_count == 1

    def test_single_required_header_below_threshold(self):
        wb = _workbook([
            _sheet("Sheet1", rows=[
                _row(1, ["岗位名称", "其他列1", "其他列2"]),
                _row(2, ["x", "y", "z"]),
            ]),
        ])
        result = detect_job_demand(wb)
        # Hits 1 required, 0 optional — must fall in candidate range so the
        # dispatcher downgrades it.
        assert 0 < result.confidence < DEFAULT_AUTO_ADMIT_THRESHOLD

    def test_no_required_header_returns_zero_confidence(self):
        wb = _workbook([
            _sheet("Sheet1", rows=[
                _row(1, ["unrelated", "headers", "only"]),
                _row(2, ["a", "b", "c"]),
            ]),
        ])
        result = detect_job_demand(wb)
        assert result.confidence == 0.0

    def test_empty_workbook_returns_zero(self):
        result = detect_job_demand(_workbook([]))
        assert result.confidence == 0.0

    def test_english_aliases_match(self):
        # Aliases are case-insensitive — pasting a CSV header line through
        # parse_csv yields lowercase 'job_title' / 'city' / 'company_name'.
        wb = _workbook([
            _sheet("Sheet1", rows=[
                _row(1, ["job_title", "city", "company_name", "salary"]),
                _row(2, ["Dev", "Tokyo", "ACME", "100k"]),
            ]),
        ])
        result = detect_job_demand(wb)
        assert result.confidence >= DEFAULT_AUTO_ADMIT_THRESHOLD


# ---------------------------------------------------------------------------
# Detector: PGSD ability_analysis
# ---------------------------------------------------------------------------


class TestDetectAbilityAnalysisPgsdSynthetic:
    def test_full_pgsd_signal_yields_high_confidence(self):
        # 4 categories + 4 code prefixes + 2 per-task sheets + overview sheet.
        wb = _workbook([
            _sheet("典型工作任务和工作内容分析表", rows=[
                _row(1, ["典型工作任务和工作内容分析表"]),
            ], sheet_index=0),
            _sheet("1.数据采集", sheet_index=1, rows=[
                _row(1, ["能力分析表"]),
                _row(5, ["职业能力", "P-1.1.1", "..."]),
                _row(18, ["通用能力", "G-1.1", "..."]),
                _row(22, ["社会能力", "S-1.1", "..."]),
                _row(29, ["发展能力", "D-1.1", "..."]),
            ]),
            _sheet("2.数据标注", sheet_index=2, rows=[
                _row(5, ["职业能力", "P-2.1.1"]),
            ]),
        ])
        result = detect_ability_analysis_pgsd(wb)
        assert result.record_type == "occupational_ability_analysis"
        assert result.domain_profile == "ability_analysis.pgsd.v1"
        assert result.analysis_model == "PGSD"
        assert result.confidence >= DEFAULT_AUTO_ADMIT_THRESHOLD
        assert set(result.evidence.matched_categories) == {
            "职业能力", "通用能力", "社会能力", "发展能力",
        }
        assert set(result.evidence.matched_code_prefixes) == {"P", "G", "S", "D"}

    def test_zhiye_jineng_alias_normalises_to_zhiye_nengli(self):
        # Decision 1 (settled): "职业技能" is an alias of canonical "职业能力".
        # The detector must count both as the same category so legacy
        # tables don't lose the P bucket.
        wb = _workbook([
            _sheet("1.x", sheet_index=0, rows=[
                _row(1, ["职业技能"]),  # alias form
                _row(2, ["通用能力"]),
                _row(3, ["社会能力"]),
                _row(4, ["发展能力"]),
                _row(5, ["P-1.1.1"]),
                _row(6, ["G-1.1"]),
                _row(7, ["S-1.1"]),
                _row(8, ["D-1.1"]),
            ]),
        ])
        result = detect_ability_analysis_pgsd(wb)
        # The detector emits the CANONICAL form so downstream code never
        # has to special-case the alias.
        assert "职业能力" in result.evidence.matched_categories
        assert "职业技能" not in result.evidence.matched_categories

    def test_single_category_low_confidence(self):
        wb = _workbook([
            _sheet("1.x", sheet_index=0, rows=[
                _row(1, ["职业能力", "P-1.1.1"]),
            ]),
        ])
        result = detect_ability_analysis_pgsd(wb)
        # 1/4 categories + 1/4 prefixes + 1 per-task sheet — should land
        # below the auto-admit threshold so the dispatcher downgrades to
        # candidate.
        assert result.confidence > 0
        assert result.confidence < DEFAULT_AUTO_ADMIT_THRESHOLD

    def test_no_pgsd_signal_returns_zero(self):
        wb = _workbook([
            _sheet("Sheet1", rows=[
                _row(1, ["岗位名称", "城市"]),
                _row(2, ["A", "B"]),
            ]),
        ])
        result = detect_ability_analysis_pgsd(wb)
        assert result.confidence == 0.0

    def test_empty_workbook_returns_zero(self):
        result = detect_ability_analysis_pgsd(_workbook([]))
        assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class TestDispatcher:
    def test_job_demand_workbook_dispatched_to_job_demand(self):
        wb = _workbook([
            _sheet("Sheet1", rows=[
                _row(1, ["岗位名称", "城市", "公司名称", "薪资", "学历要求", "岗位描述"]),
                _row(2, ["平面设计师", "上海", "ACME", "10k", "本科", "..."]),
            ]),
        ])
        result = detect(wb)
        assert result.record_type == "job_demand_dataset"
        assert result.confidence >= DEFAULT_AUTO_ADMIT_THRESHOLD

    def test_pgsd_workbook_dispatched_to_ability_analysis(self):
        wb = _workbook([
            _sheet("典型工作任务和工作内容分析表", sheet_index=0, rows=[
                _row(1, ["典型工作任务和工作内容分析表"]),
            ]),
            _sheet("1.数据采集", sheet_index=1, rows=[
                _row(1, ["职业能力", "通用能力", "社会能力", "发展能力"]),
                _row(2, ["P-1.1.1", "G-1.1", "S-1.1", "D-1.1"]),
            ]),
        ])
        result = detect(wb)
        assert result.record_type == "occupational_ability_analysis"
        assert result.analysis_model == "PGSD"

    def test_low_confidence_job_demand_downgrades_to_candidate(self):
        # One required header only — high enough to register but well below
        # the auto-admit threshold.
        wb = _workbook([
            _sheet("Sheet1", rows=[
                _row(1, ["岗位名称", "filler1"]),
                _row(2, ["dev", "x"]),
            ]),
        ])
        result = detect(wb)
        assert result.record_type == "job_demand_dataset_candidate"
        # Domain / profile remain — only record_type is downgraded.
        assert result.domain_profile == "job_demand.v1"

    def test_low_confidence_pgsd_downgrades_to_candidate(self):
        wb = _workbook([
            _sheet("1.x", sheet_index=0, rows=[
                _row(1, ["职业能力", "P-1.1.1"]),
            ]),
        ])
        result = detect(wb)
        assert result.record_type == "occupational_ability_analysis_candidate"
        assert result.analysis_model == "PGSD"

    def test_no_signal_falls_back_to_generic_table(self):
        wb = _workbook([
            _sheet("Sheet1", rows=[
                _row(1, ["random", "headers", "only"]),
                _row(2, ["1", "2", "3"]),
            ]),
        ])
        result = detect(wb)
        assert result.record_type == "generic_table_dataset"

    def test_higher_confidence_detector_wins(self):
        # A workbook can carry weak signals from BOTH detectors — pick best.
        # Here job_demand has 3 required + lots of optional → ~0.9.
        # PGSD has only "职业能力" + "P-1.1.1" → ~0.2.
        wb = _workbook([
            _sheet("Sheet1", rows=[
                _row(1, [
                    "岗位名称", "城市", "公司名称",
                    "薪资", "学历要求", "岗位描述", "发布时间",
                ]),
                _row(2, ["X", "Y", "Z", "10k", "本科", "P-1.1.1 in 描述", "2025"]),
                # The cell "职业能力" sneaks in but shouldn't tip the scales.
                _row(3, ["A", "B", "C", "1k", "高中", "职业能力 mention", "2024"]),
            ]),
        ])
        result = detect(wb)
        assert result.record_type == "job_demand_dataset"

    def test_explicit_threshold_override(self):
        # Caller can raise the threshold to be more conservative.
        wb = _workbook([
            _sheet("Sheet1", rows=[
                _row(1, ["岗位名称", "城市", "公司名称", "薪资"]),
                _row(2, ["a", "b", "c", "d"]),
            ]),
        ])
        # With threshold 0.99 the result should drop to candidate.
        result = detect(wb, threshold=0.99)
        assert result.record_type == "job_demand_dataset_candidate"

    def test_empty_workbook_returns_generic_table_fallback(self):
        # Nothing to detect, but the function MUST not raise — worker will
        # park it in review queue via the generic_table record_type.
        result = detect(_workbook([]))
        assert result.record_type == "generic_table_dataset"

    def test_detector_version_pinned_on_result(self):
        wb = _workbook([_sheet("Sheet1", rows=[_row(1, ["a"])])])
        result = detect(wb)
        assert result.detector_version == DETECTOR_VERSION


# ---------------------------------------------------------------------------
# Integration: real samples
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not SAMPLE_JOB_DEMAND.exists(), reason="sample missing")
class TestSampleJobDemandIntegration:
    @pytest.fixture(scope="class")
    def result(self):
        wb = parse_xlsx(
            SAMPLE_JOB_DEMAND.read_bytes(),
            source_filename=SAMPLE_JOB_DEMAND.name,
        )
        return detect(wb)

    def test_classified_as_job_demand_dataset(self, result):
        assert result.record_type == "job_demand_dataset"
        assert result.domain_profile == "job_demand.v1"

    def test_high_confidence(self, result):
        # Sample 1 carries 3 required + 8+ optional headers → confidence
        # should clear 0.85 with margin.
        assert result.confidence >= 0.90, (
            f"sample 1 confidence dropped to {result.confidence}; "
            "either aliases drifted or scoring needs tuning"
        )

    def test_evidence_captures_real_headers(self, result):
        # Spot-check a few headers that we know live in the sample.
        for h in ["岗位名称", "城市", "公司名称"]:
            assert h in result.evidence.matched_headers


@pytest.mark.skipif(not SAMPLE_ABILITY.exists(), reason="sample missing")
class TestSampleAbilityAnalysisIntegration:
    @pytest.fixture(scope="class")
    def result(self):
        wb = parse_xlsx(
            SAMPLE_ABILITY.read_bytes(),
            source_filename=SAMPLE_ABILITY.name,
        )
        return detect(wb)

    def test_classified_as_pgsd_ability_analysis(self, result):
        assert result.record_type == "occupational_ability_analysis"
        assert result.domain_profile == "ability_analysis.pgsd.v1"
        assert result.analysis_model == "PGSD"

    def test_high_confidence(self, result):
        # Sample 2 carries the full PGSD signal: all four categories +
        # all four code prefixes + four per-task sheets + an overview
        # sheet. Should comfortably clear 0.85.
        assert result.confidence >= 0.90, (
            f"sample 2 confidence dropped to {result.confidence}; "
            "PGSD scoring regressed"
        )

    def test_all_four_pgsd_categories_matched(self, result):
        assert set(result.evidence.matched_categories) == {
            "职业能力", "通用能力", "社会能力", "发展能力",
        }

    def test_all_four_code_prefixes_matched(self, result):
        assert set(result.evidence.matched_code_prefixes) == {"P", "G", "S", "D"}
