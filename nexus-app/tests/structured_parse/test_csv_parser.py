"""Tests for `structured_parse.csv_parser`.

Covers:
  - encoding fallback (utf-8 → utf-8-sig → gb18030)
  - BOM stripping
  - Multi-line quoted fields (RFC 4180)
  - Index-column drop (序号 / No.)
  - Placeholder row flagging
  - Empty / malformed inputs
  - Source variants: bytes / str / Path / file-like
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from nexus_app.structured_parse.csv_parser import PARSER_VERSION, parse_csv
from nexus_app.structured_parse.exceptions import (
    CorruptSourceError,
    StructuredParseError,
)


class TestParserVersion:
    def test_parser_version_pinned(self):
        assert PARSER_VERSION == "csv_parser.v1"


# ---------------------------------------------------------------------------
# Basic row / column extraction
# ---------------------------------------------------------------------------


class TestBasicParsing:
    def test_simple_two_column_two_row(self):
        text = "a,b\n1,2\n"
        result = parse_csv(text)
        assert len(result.sheets) == 1
        sheet = result.sheets[0]
        assert sheet.name == "csv"
        assert sheet.column_count == 2
        assert sheet.row_count == 2

        row0 = sheet.rows[0]
        assert [c.value for c in row0.cells] == ["a", "b"]
        assert [c.column_letter for c in row0.cells] == ["A", "B"]

        row1 = sheet.rows[1]
        assert [c.value for c in row1.cells] == ["1", "2"]

    def test_custom_sheet_name(self):
        result = parse_csv("a,b\n1,2", sheet_name="orders")
        assert result.sheets[0].name == "orders"


# ---------------------------------------------------------------------------
# Encoding handling
# ---------------------------------------------------------------------------


class TestEncoding:
    def test_utf8_bytes(self):
        text = "name,email\n张三,zs@example.com\n"
        result = parse_csv(text.encode("utf-8"))
        assert result.sheets[0].rows[1].cells[0].value == "张三"

    def test_utf8_bom_stripped(self):
        # `encode("utf-8-sig")` already prepends the BOM — the source text
        # itself must NOT include a manual \ufeff or we end up with a double BOM.
        text = "name,city\n张三,北京\n"
        result = parse_csv(text.encode("utf-8-sig"))
        # The BOM must not leak into the first header cell value
        assert result.sheets[0].rows[0].cells[0].value == "name"
        assert result.sheets[0].rows[1].cells[0].value == "张三"

    def test_gb18030_fallback(self):
        text = "姓名,城市\n李四,上海\n"
        result = parse_csv(text.encode("gb18030"))
        assert result.sheets[0].rows[0].cells[0].value == "姓名"
        assert result.sheets[0].rows[1].cells[1].value == "上海"

    def test_explicit_encoding_overrides_fallback(self):
        # Bytes that decode under gb18030 but NOT under utf-8: characters with
        # high-byte sequences valid in gb18030. We force gb18030.
        text = "姓名\n王五\n"
        result = parse_csv(text.encode("gb18030"), encoding="gb18030")
        assert result.sheets[0].rows[1].cells[0].value == "王五"

    def test_unknown_encoding_raises_corrupt(self):
        with pytest.raises(CorruptSourceError):
            # Invalid latin1 binary that's definitely not any of our candidates.
            parse_csv(bytes([0xC3, 0x28, 0xFF]))


# ---------------------------------------------------------------------------
# RFC 4180 quoting / multiline
# ---------------------------------------------------------------------------


class TestRfc4180Quoting:
    def test_quoted_comma_kept(self):
        result = parse_csv('a,b\n"hello, world",2\n')
        assert result.sheets[0].rows[1].cells[0].value == "hello, world"
        assert result.sheets[0].rows[1].cells[1].value == "2"

    def test_multiline_quoted_field_preserved(self):
        text = 'a,b\n"line1\nline2\nline3",2\n'
        result = parse_csv(text)
        cell = result.sheets[0].rows[1].cells[0]
        assert cell.value == "line1\nline2\nline3"
        assert cell.is_multiline is True

    def test_doubled_quote_unescaped(self):
        text = 'a\n"say ""hi"""\n'
        result = parse_csv(text)
        assert result.sheets[0].rows[1].cells[0].value == 'say "hi"'

    def test_crlf_line_endings_handled(self):
        text = "a,b\r\n1,2\r\n3,4\r\n"
        result = parse_csv(text)
        assert result.sheets[0].row_count == 3


# ---------------------------------------------------------------------------
# Index column drop
# ---------------------------------------------------------------------------


class TestIndexColumnDrop:
    @pytest.mark.parametrize("alias", ["序号", "No.", "id", "#"])
    def test_first_row_alias_drops_column(self, alias):
        text = f"{alias},name\n1,a\n2,b\n"
        result = parse_csv(text)
        sheet = result.sheets[0]
        assert sheet.dropped_index_columns == [1]
        # remaining cells start at column 2 (column_letter='B')
        for row in sheet.rows:
            assert row.cells[0].column == 2
            assert row.cells[0].column_letter == "B"

    def test_non_alias_keeps_all_columns(self):
        text = "name,city\nzs,bj\n"
        result = parse_csv(text)
        assert result.sheets[0].dropped_index_columns == []

    def test_custom_alias_overrides_default(self):
        text = "Lp.,name\n1,a\n"
        result = parse_csv(text, index_column_aliases=frozenset({"Lp."}))
        assert result.sheets[0].dropped_index_columns == [1]


# ---------------------------------------------------------------------------
# Placeholder rows
# ---------------------------------------------------------------------------


class TestPlaceholderRows:
    def test_chinese_ellipsis_flags_row(self):
        text = "a,b\n1,2\n……,\n3,4\n"
        result = parse_csv(text)
        rows = result.sheets[0].rows
        assert rows[0].is_placeholder_candidate is False
        # Row containing "……" anywhere → flagged
        assert any(r.is_placeholder_candidate for r in rows)

    def test_placeholder_rows_not_filtered(self):
        text = "a\nreal\n……\n"
        result = parse_csv(text)
        # 3 rows (header + 1 + placeholder) — none removed
        assert result.sheets[0].row_count == 3


# ---------------------------------------------------------------------------
# Empty values
# ---------------------------------------------------------------------------


class TestEmptyValues:
    def test_blank_cell_is_none(self):
        text = "a,b\n,2\n"
        cell0 = parse_csv(text).sheets[0].rows[1].cells[0]
        assert cell0.value is None

    def test_fully_empty_row_marked_empty(self):
        text = "a,b\n,\n3,4\n"
        result = parse_csv(text)
        assert result.sheets[0].rows[1].is_empty is True
        assert result.sheets[0].rows[2].is_empty is False

    def test_empty_input_yields_zero_rows(self):
        result = parse_csv("")
        assert result.sheets[0].row_count == 0
        assert result.sheets[0].column_count == 0


# ---------------------------------------------------------------------------
# Source variants
# ---------------------------------------------------------------------------


class TestSourceVariants:
    def test_str_input(self):
        result = parse_csv("a,b\n1,2")
        assert result.sheets[0].row_count == 2

    def test_bytes_input(self):
        result = parse_csv(b"a,b\n1,2")
        assert result.sheets[0].row_count == 2

    def test_binary_filelike_input(self):
        result = parse_csv(io.BytesIO(b"a,b\n1,2"))
        assert result.sheets[0].row_count == 2

    def test_text_filelike_input(self):
        result = parse_csv(io.StringIO("a,b\n1,2"))
        assert result.sheets[0].row_count == 2

    def test_path_input(self, tmp_path: Path):
        p = tmp_path / "data.csv"
        p.write_text("a,b\n1,2", encoding="utf-8")
        result = parse_csv(p)
        assert result.sheets[0].row_count == 2

    def test_path_string_input(self, tmp_path: Path):
        p = tmp_path / "data.csv"
        p.write_text("name\nzs", encoding="utf-8")
        result = parse_csv(str(p))
        # Path-string detection should treat it as a path, not as csv text
        assert result.sheets[0].rows[1].cells[0].value == "zs"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_custom_delimiter(self):
        result = parse_csv("a;b\n1;2", delimiter=";")
        assert [c.value for c in result.sheets[0].rows[1].cells] == ["1", "2"]

    def test_ragged_rows_padded_to_max_width(self):
        # Second row is short — output should still produce 3 cells with the
        # missing cell as None.
        text = "a,b,c\n1,2\n3,4,5\n"
        result = parse_csv(text)
        row1 = result.sheets[0].rows[1]
        assert len(row1.cells) == 3
        assert row1.cells[2].value is None

    def test_unknown_timezone_raises(self):
        with pytest.raises(StructuredParseError):
            parse_csv("a,b\n1,2", timezone_name="Not/A_Real_Zone")

    def test_workbook_metadata(self):
        result = parse_csv(
            "a,b\n1,2", source_filename="x.csv", source_mime_type="text/csv"
        )
        assert result.parser_version == PARSER_VERSION
        assert result.source_filename == "x.csv"
        assert result.source_mime_type == "text/csv"
        assert result.timezone == "Asia/Shanghai"
        assert result.sheets[0].merged_ranges == []
