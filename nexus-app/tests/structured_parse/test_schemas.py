"""Tests for `structured_parse.schemas` Pydantic models.

These tests pin field defaults, the get_sheet lookup helper, and the
mutually-exclusive merge flag semantics that downstream consumers rely on.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from nexus_app.structured_parse.schemas import (
    ParsedCell,
    ParsedRow,
    ParsedSheet,
    ParsedWorkbook,
)


class TestParsedCellDefaults:
    def test_minimal_construction(self):
        cell = ParsedCell(column=1, column_letter="A", value="x")
        assert cell.column == 1
        assert cell.column_letter == "A"
        assert cell.value == "x"
        assert cell.raw_text is None
        assert cell.is_merged_origin is False
        assert cell.is_filled_from_merge is False
        assert cell.merged_range is None
        assert cell.is_multiline is False

    @pytest.mark.parametrize("value", [None, "", "text", 42, 3.14, True])
    def test_accepts_native_cell_value_types(self, value):
        cell = ParsedCell(column=1, column_letter="A", value=value)
        assert cell.value == value


class TestParsedRowDefaults:
    def test_empty_row(self):
        row = ParsedRow(row_index=1)
        assert row.row_index == 1
        assert row.cells == []
        assert row.is_placeholder_candidate is False
        assert row.is_empty is False

    def test_row_with_cells(self):
        row = ParsedRow(
            row_index=2,
            cells=[
                ParsedCell(column=1, column_letter="A", value="a"),
                ParsedCell(column=2, column_letter="B", value="b"),
            ],
        )
        assert len(row.cells) == 2


class TestParsedSheetDefaults:
    def test_empty_sheet(self):
        sheet = ParsedSheet(name="Sheet1", sheet_index=0)
        assert sheet.name == "Sheet1"
        assert sheet.sheet_index == 0
        assert sheet.rows == []
        assert sheet.merged_ranges == []
        assert sheet.column_count == 0
        assert sheet.row_count == 0
        assert sheet.dropped_index_columns == []


class TestParsedWorkbook:
    def test_workbook_construction(self):
        wb = ParsedWorkbook(
            parser_version="xlsx_parser.v1",
            parsed_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
            timezone="Asia/Shanghai",
            sheets=[
                ParsedSheet(name="A", sheet_index=0),
                ParsedSheet(name="B", sheet_index=1),
            ],
        )
        assert wb.parser_version == "xlsx_parser.v1"
        assert len(wb.sheets) == 2

    def test_get_sheet_by_name(self):
        wb = ParsedWorkbook(
            parser_version="xlsx_parser.v1",
            parsed_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
            timezone="UTC",
            sheets=[
                ParsedSheet(name="alpha", sheet_index=0),
                ParsedSheet(name="beta", sheet_index=1),
            ],
        )
        assert wb.get_sheet("alpha").sheet_index == 0
        assert wb.get_sheet("beta").sheet_index == 1
        assert wb.get_sheet("missing") is None
