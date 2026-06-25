"""B3.5 — projection from `ParsedWorkbook` to contract-shape `record_body`.

These tests pin the contract the B4 / B6 writers depend on:

- `project_to_record_body(raw_payload, profile_dict=None)` returns the raw
  payload unchanged (legacy JSON ingestion stays functional).
- `domain_profile=job_demand.v1` returns `{dataset, records}` where each
  record carries the canonical field names from
  `pipeline_b_contract_freeze.md §5.0.2`.
- `domain_profile=ability_analysis.pgsd.v1` returns `{analysis, tasks}` with
  per-task work_contents + general_abilities split by code prefix.
- Unknown `domain_profile` returns the raw payload (dispatcher will skip,
  but the projector itself never raises).
"""
from __future__ import annotations

from nexus_app.structured_parse.record_body_adapter import project_to_record_body


# ---------------------------------------------------------------------------
# Helpers — synthesize the minimum ParsedWorkbook-shape dicts the projector
# reads. Using dicts rather than instantiating Pydantic models keeps tests
# decoupled from incidental schema additions.
# ---------------------------------------------------------------------------

def _cell(column: int, value, *, column_letter: str | None = None) -> dict:
    return {
        "column": column,
        "column_letter": column_letter or chr(ord("A") + column - 1),
        "value": value,
        "raw_text": None,
        "is_merged_origin": False,
        "is_filled_from_merge": False,
        "merged_range": None,
        "is_multiline": False,
    }


def _row(row_index: int, values: list, *, is_empty: bool = False,
         is_placeholder: bool = False) -> dict:
    return {
        "row_index": row_index,
        "cells": [_cell(i + 1, v) for i, v in enumerate(values)],
        "is_placeholder_candidate": is_placeholder,
        "is_empty": is_empty,
    }


def _sheet(name: str, rows: list[dict]) -> dict:
    return {
        "name": name,
        "sheet_index": 0,
        "rows": rows,
        "merged_ranges": [],
        "column_count": max((len(r["cells"]) for r in rows), default=0),
        "row_count": len(rows),
        "dropped_index_columns": [],
    }


def _workbook(*sheets: dict) -> dict:
    return {
        "parser_version": "xlsx_parser.v1",
        "parsed_at": "2026-06-25T00:00:00+00:00",
        "source_filename": "test.xlsx",
        "source_mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "timezone": "Asia/Shanghai",
        "sheets": list(sheets),
    }


# ---------------------------------------------------------------------------
# Passthrough (no profile / unknown profile / JSON payload)
# ---------------------------------------------------------------------------

class TestPassthrough:
    def test_no_profile_returns_payload_unchanged(self):
        raw = {"sheets": [], "anything": "kept"}
        out = project_to_record_body(raw, profile_dict=None)
        assert out is raw

    def test_unknown_profile_returns_payload_unchanged(self):
        raw = {"sheets": [], "x": 1}
        out = project_to_record_body(raw, {"domain_profile": "not_a_profile.v9"})
        assert out is raw

    def test_json_payload_with_record_type_only_passes_through(self):
        # Legacy JSON ingestion: profile carries record_type but no
        # canonicalised domain_profile that the projector knows about.
        raw = {"foo": "bar"}
        out = project_to_record_body(raw, {"record_type": "generic_table_dataset"})
        assert out is raw


# ---------------------------------------------------------------------------
# job_demand.v1 projection
# ---------------------------------------------------------------------------

class TestJobDemandProjection:
    def _wb(self) -> dict:
        return _workbook(_sheet("Sheet1", [
            _row(1, ["岗位名称", "城市", "公司名称", "薪资", "学历要求", "企业规模"]),
            _row(2, ["数据分析师", "北京", "字节跳动", "15k-25k", "本科", "1000人以上"]),
            _row(3, ["数据工程师", "上海", "美团", "20k-35k", "硕士", "500-999人"]),
        ]))

    def test_returns_dataset_and_records_keys(self):
        out = project_to_record_body(self._wb(), {"domain_profile": "job_demand.v1"})
        assert set(out.keys()) == {"dataset", "records"}

    def test_records_have_canonical_field_names(self):
        out = project_to_record_body(self._wb(), {"domain_profile": "job_demand.v1"})
        records = out["records"]
        assert len(records) == 2
        first = records[0]
        assert first["job_title"] == "数据分析师"
        assert first["city"] == "北京"
        assert first["company_name"] == "字节跳动"
        assert first["salary_text"] == "15k-25k"
        assert first["education_requirement"] == "本科"
        assert first["enterprise_size"] == "1000人以上"

    def test_each_record_carries_trace_and_source_record_key(self):
        out = project_to_record_body(self._wb(), {"domain_profile": "job_demand.v1"})
        records = out["records"]
        assert records[0]["trace"] == {"sheet": "Sheet1", "row": 2}
        assert records[0]["source_record_key"] == "Sheet1#row2"

    def test_dataset_source_channel_defaults_to_excel_upload(self):
        out = project_to_record_body(self._wb(), {"domain_profile": "job_demand.v1"})
        assert out["dataset"]["source_channel"] == "excel_upload"

    def test_dataset_record_count_matches(self):
        out = project_to_record_body(self._wb(), {"domain_profile": "job_demand.v1"})
        assert out["dataset"]["record_count"] == 2

    def test_placeholder_rows_dropped(self):
        wb = _workbook(_sheet("Sheet1", [
            _row(1, ["岗位名称", "城市", "公司名称"]),
            _row(2, ["数据分析师", "北京", "字节"]),
            _row(3, ["……", "", ""], is_placeholder=True),
            _row(4, ["", "", ""], is_empty=True),
            _row(5, ["数据工程师", "上海", "美团"]),
        ]))
        out = project_to_record_body(wb, {"domain_profile": "job_demand.v1"})
        assert len(out["records"]) == 2
        assert out["records"][0]["job_title"] == "数据分析师"
        assert out["records"][1]["job_title"] == "数据工程师"

    def test_sheet_without_known_headers_skipped(self):
        wb = _workbook(_sheet("Random", [
            _row(1, ["X", "Y", "Z"]),
            _row(2, ["1", "2", "3"]),
        ]))
        out = project_to_record_body(wb, {"domain_profile": "job_demand.v1"})
        assert out["records"] == []
        assert out["dataset"]["record_count"] == 0

    def test_numeric_coercion_for_salary_bounds(self):
        wb = _workbook(_sheet("Sheet1", [
            _row(1, ["岗位名称", "城市", "公司名称", "最低薪资", "最高薪资"]),
            _row(2, ["数据分析师", "北京", "字节", "15000", "25000"]),
        ]))
        out = project_to_record_body(wb, {"domain_profile": "job_demand.v1"})
        rec = out["records"][0]
        assert rec["salary_min"] == 15000
        assert rec["salary_max"] == 25000

    def test_empty_strings_treated_as_absent(self):
        wb = _workbook(_sheet("Sheet1", [
            _row(1, ["岗位名称", "城市", "公司名称", "学历要求"]),
            _row(2, ["数据分析师", "北京", "字节", "   "]),
        ]))
        out = project_to_record_body(wb, {"domain_profile": "job_demand.v1"})
        rec = out["records"][0]
        assert "education_requirement" not in rec  # absent, not empty-string

    def test_profile_evidence_surfaces_to_dataset(self):
        wb = self._wb()
        profile = {
            "domain_profile": "job_demand.v1",
            "evidence": {"major_name": "大数据技术应用", "industry_name": "信息技术"},
        }
        out = project_to_record_body(wb, profile)
        assert out["dataset"]["major_name"] == "大数据技术应用"
        assert out["dataset"]["industry_name"] == "信息技术"

    def test_multiple_sheets_combined(self):
        wb = _workbook(
            _sheet("S1", [
                _row(1, ["岗位名称", "城市", "公司名称"]),
                _row(2, ["A岗位", "北京", "甲公司"]),
            ]),
            _sheet("S2", [
                _row(1, ["岗位名称", "城市", "公司名称"]),
                _row(2, ["B岗位", "上海", "乙公司"]),
            ]),
        )
        out = project_to_record_body(wb, {"domain_profile": "job_demand.v1"})
        assert len(out["records"]) == 2
        assert {r["job_title"] for r in out["records"]} == {"A岗位", "B岗位"}


# ---------------------------------------------------------------------------
# ability_analysis.pgsd.v1 projection
# ---------------------------------------------------------------------------

class TestAbilityAnalysisProjection:
    def _pgsd_wb(self) -> dict:
        # Sheet name "1.数据采集" matches PGSD_SHEET_NAME_PATTERN.
        # Sample-2 layout: col A = category name, col B = ability code, col C = content.
        return _workbook(_sheet("1.数据采集", [
            _row(1, ["类别", "能力编码", "能力内容"]),  # header (ignored by extractor)
            _row(2, ["职业能力", "P-1.1.1", "能用工具采集日志数据"]),
            _row(3, ["职业能力", "P-1.1.2", "能配置采集 agent"]),
            _row(4, ["职业能力", "P-1.2.1", "能用 API 采集数据"]),
            _row(5, ["通用能力", "G-1.1", "团队协作"]),
            _row(6, ["社会能力", "S-1.1", "沟通能力"]),
            _row(7, ["发展能力", "D-1.1", "持续学习"]),
        ]))

    def test_returns_analysis_and_tasks_keys(self):
        out = project_to_record_body(
            self._pgsd_wb(), {"domain_profile": "ability_analysis.pgsd.v1"}
        )
        assert set(out.keys()) == {"analysis", "tasks"}

    def test_task_code_and_name_parsed_from_sheet_name(self):
        out = project_to_record_body(
            self._pgsd_wb(), {"domain_profile": "ability_analysis.pgsd.v1"}
        )
        assert len(out["tasks"]) == 1
        task = out["tasks"][0]
        assert task["task_code"] == "1"
        assert task["task_name"] == "数据采集"
        assert task["display_order"] == 1

    def test_p_abilities_grouped_by_work_content_code(self):
        out = project_to_record_body(
            self._pgsd_wb(), {"domain_profile": "ability_analysis.pgsd.v1"}
        )
        task = out["tasks"][0]
        wcs = {wc["content_code"]: wc for wc in task["work_contents"]}
        # P-1.1.1 + P-1.1.2 → content_code "1.1"; P-1.2.1 → "1.2".
        assert set(wcs.keys()) == {"1.1", "1.2"}
        assert len(wcs["1.1"]["abilities"]) == 2
        assert len(wcs["1.2"]["abilities"]) == 1
        assert wcs["1.1"]["abilities"][0]["ability_code"] == "P-1.1.1"
        assert wcs["1.1"]["abilities"][0]["ability_major_category_code"] == "P"
        assert "采集日志" in wcs["1.1"]["abilities"][0]["ability_content"]

    def test_general_abilities_split_by_category(self):
        out = project_to_record_body(
            self._pgsd_wb(), {"domain_profile": "ability_analysis.pgsd.v1"}
        )
        task = out["tasks"][0]
        gen = task["general_abilities"]
        assert {ga["ability_code"] for ga in gen["G"]} == {"G-1.1"}
        assert {ga["ability_code"] for ga in gen["S"]} == {"S-1.1"}
        assert {ga["ability_code"] for ga in gen["D"]} == {"D-1.1"}

    def test_analysis_counts_aggregate_across_tasks(self):
        out = project_to_record_body(
            self._pgsd_wb(), {"domain_profile": "ability_analysis.pgsd.v1"}
        )
        analysis = out["analysis"]
        assert analysis["analysis_model"] == "PGSD"
        assert analysis["task_count"] == 1
        assert analysis["work_content_count"] == 2  # 1.1, 1.2
        assert analysis["ability_item_count"] == 6  # 3 P + G + S + D

    def test_non_pgsd_sheets_ignored(self):
        wb = _workbook(
            _sheet("OverviewSheet", [_row(1, ["x"])]),
            _sheet("1.数据采集", [
                _row(1, ["类别", "能力编码", "能力内容"]),
                _row(2, ["职业能力", "P-1.1.1", "x"]),
            ]),
            _sheet("RandomGenericSheet", [_row(1, ["x", "y"])]),
        )
        out = project_to_record_body(wb, {"domain_profile": "ability_analysis.pgsd.v1"})
        assert len(out["tasks"]) == 1

    def test_multiple_task_sheets_create_multiple_tasks(self):
        wb = _workbook(
            _sheet("1.数据采集", [
                _row(1, ["类别", "能力编码", "能力内容"]),
                _row(2, ["职业能力", "P-1.1.1", "x"]),
            ]),
            _sheet("2.数据清洗", [
                _row(1, ["类别", "能力编码", "能力内容"]),
                _row(2, ["职业能力", "P-2.1.1", "y"]),
            ]),
        )
        out = project_to_record_body(wb, {"domain_profile": "ability_analysis.pgsd.v1"})
        codes = sorted(t["task_code"] for t in out["tasks"])
        assert codes == ["1", "2"]

    def test_placeholder_rows_ignored(self):
        wb = _workbook(_sheet("1.数据采集", [
            _row(1, ["类别", "能力编码", "能力内容"]),
            _row(2, ["职业能力", "P-1.1.1", "x"]),
            _row(3, ["……", "", ""], is_placeholder=True),
            _row(4, ["", "", ""], is_empty=True),
            _row(5, ["职业能力", "P-1.1.2", "y"]),
        ]))
        out = project_to_record_body(wb, {"domain_profile": "ability_analysis.pgsd.v1"})
        wc = out["tasks"][0]["work_contents"][0]
        assert len(wc["abilities"]) == 2

    def test_rows_without_ability_code_ignored(self):
        wb = _workbook(_sheet("1.数据采集", [
            _row(1, ["类别", "能力编码", "能力内容"]),
            _row(2, ["职业能力", "not-a-code", "garbage"]),
            _row(3, ["职业能力", "P-1.1.1", "x"]),
        ]))
        out = project_to_record_body(wb, {"domain_profile": "ability_analysis.pgsd.v1"})
        wc = out["tasks"][0]["work_contents"][0]
        assert len(wc["abilities"]) == 1
        assert wc["abilities"][0]["ability_code"] == "P-1.1.1"
