"""Tests for `structured_parse.json_parser`.

Covers:
  - Top-level array of objects
  - Wrapper object with `records` / `items` / `data` / `rows` key
  - Single object as a single-row dataset
  - Header derivation (union of record keys in first-occurrence order)
  - Sparse records (missing keys → None cells)
  - Nested values (list / dict) serialised to JSON strings
  - Index-column drop / placeholder flagging
  - Failure paths: bad JSON, non-dict array elements, unsupported top-level types
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from nexus_app.structured_parse.exceptions import (
    CorruptSourceError,
    EmptySourceError,
    StructuredParseError,
)
from nexus_app.structured_parse.json_parser import PARSER_VERSION, parse_json


class TestParserVersion:
    def test_parser_version_pinned(self):
        assert PARSER_VERSION == "json_parser.v1"


# ---------------------------------------------------------------------------
# Top-level array
# ---------------------------------------------------------------------------


class TestTopLevelArray:
    def test_array_of_objects(self):
        text = json.dumps([
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ])
        result = parse_json(text)
        sheet = result.sheets[0]
        # Row 1 = header, rows 2-3 = data
        assert sheet.row_count == 3
        assert [c.value for c in sheet.rows[0].cells] == ["name", "age"]
        assert [c.value for c in sheet.rows[1].cells] == ["Alice", 30]
        assert [c.value for c in sheet.rows[2].cells] == ["Bob", 25]

    def test_sparse_records_pad_with_none(self):
        text = json.dumps([
            {"name": "Alice", "age": 30},
            {"name": "Bob"},  # missing age
            {"name": "Carol", "age": 40, "city": "Beijing"},  # extra column
        ])
        result = parse_json(text)
        sheet = result.sheets[0]
        # header columns: name, age, city (first-occurrence order)
        assert [c.value for c in sheet.rows[0].cells] == ["name", "age", "city"]
        # Bob row: age=None, city=None
        bob = sheet.rows[2]
        assert bob.cells[0].value == "Bob"
        assert bob.cells[1].value is None
        assert bob.cells[2].value is None

    def test_array_with_non_object_raises(self):
        text = json.dumps([{"k": 1}, "not an object", {"k": 3}])
        with pytest.raises(CorruptSourceError, match="not an object"):
            parse_json(text)

    def test_empty_array_raises_empty_source(self):
        with pytest.raises(EmptySourceError):
            parse_json("[]")


# ---------------------------------------------------------------------------
# Wrapper objects
# ---------------------------------------------------------------------------


class TestWrapperObject:
    @pytest.mark.parametrize("key", ["records", "items", "data", "rows"])
    def test_default_wrapper_keys_resolved(self, key):
        text = json.dumps({key: [{"k": "v"}], "meta": "ignored"})
        result = parse_json(text)
        sheet = result.sheets[0]
        assert sheet.row_count == 2
        assert sheet.rows[1].cells[0].value == "v"

    def test_first_matching_key_wins(self):
        # "records" comes before "items" in default candidates → "records" wins
        text = json.dumps({
            "items": [{"a": 1}],
            "records": [{"b": 2}],
        })
        result = parse_json(text)
        # Header from records wrapper, not items
        assert [c.value for c in result.sheets[0].rows[0].cells] == ["b"]

    def test_custom_record_path_candidates(self):
        text = json.dumps({"my_list": [{"a": 1}], "records": [{"b": 2}]})
        result = parse_json(text, record_path_candidates=("my_list",))
        assert [c.value for c in result.sheets[0].rows[0].cells] == ["a"]

    def test_wrapper_with_empty_array_falls_through(self):
        # Empty records array → falls back to single-row dict treatment;
        # the wrapper object itself becomes the lone row.
        text = json.dumps({"records": [], "name": "fallback"})
        result = parse_json(text)
        # "records" key serialised to JSON string (it's a list inside the
        # single-row payload).
        sheet = result.sheets[0]
        assert sheet.row_count == 2  # header + 1 data row
        # The first row is header, second is the dict-as-row
        header_keys = [c.value for c in sheet.rows[0].cells]
        assert "records" in header_keys
        assert "name" in header_keys


# ---------------------------------------------------------------------------
# Single-object dataset
# ---------------------------------------------------------------------------


class TestSingleObject:
    def test_single_object_is_one_row(self):
        text = json.dumps({"name": "Alice", "age": 30})
        result = parse_json(text)
        sheet = result.sheets[0]
        assert sheet.row_count == 2  # header + 1 data row
        assert sheet.rows[1].cells[0].value == "Alice"
        assert sheet.rows[1].cells[1].value == 30

    def test_empty_object_raises_empty(self):
        with pytest.raises(EmptySourceError):
            parse_json("{}")


# ---------------------------------------------------------------------------
# Nested values
# ---------------------------------------------------------------------------


class TestNestedValues:
    def test_nested_list_serialised_to_json(self):
        text = json.dumps([{"tags": ["a", "b", "c"]}])
        cell = parse_json(text).sheets[0].rows[1].cells[0]
        assert cell.value == '["a", "b", "c"]'
        assert cell.raw_text is not None  # raw repr preserved for audit

    def test_nested_dict_serialised_to_json(self):
        text = json.dumps([{"meta": {"k": "v", "n": 1}}])
        cell = parse_json(text).sheets[0].rows[1].cells[0]
        # JSON serialisation preserves the dict shape as a string
        parsed_back = json.loads(cell.value)
        assert parsed_back == {"k": "v", "n": 1}
        assert cell.raw_text is not None

    def test_bool_preserved_as_bool(self):
        cell = parse_json('[{"flag": true}]').sheets[0].rows[1].cells[0]
        assert cell.value is True

    def test_null_preserved_as_none(self):
        cell = parse_json('[{"x": null}]').sheets[0].rows[1].cells[0]
        assert cell.value is None


# ---------------------------------------------------------------------------
# Multiline / placeholder / index
# ---------------------------------------------------------------------------


class TestRowFlagging:
    def test_multiline_string_value_flags_multiline(self):
        text = json.dumps([{"desc": "line1\nline2"}])
        cell = parse_json(text).sheets[0].rows[1].cells[0]
        assert cell.is_multiline is True

    def test_placeholder_row_flagged(self):
        text = json.dumps([{"name": "real"}, {"name": "……"}])
        rows = parse_json(text).sheets[0].rows
        # row 0 = header (not flagged), row 1 = real, row 2 = placeholder
        assert rows[1].is_placeholder_candidate is False
        assert rows[2].is_placeholder_candidate is True

    def test_index_column_drop(self):
        text = json.dumps([{"序号": 1, "name": "a"}, {"序号": 2, "name": "b"}])
        sheet = parse_json(text).sheets[0]
        assert sheet.dropped_index_columns == [1]
        # Header row has 'name' as the only surviving column
        for row in sheet.rows:
            assert row.cells[0].column == 2
            assert row.cells[0].column_letter == "B"


# ---------------------------------------------------------------------------
# Source variants
# ---------------------------------------------------------------------------


class TestSourceVariants:
    def test_bytes_input(self):
        text = json.dumps([{"k": "v"}]).encode("utf-8")
        assert parse_json(text).sheets[0].row_count == 2

    def test_str_input(self):
        assert parse_json('[{"k": "v"}]').sheets[0].row_count == 2

    def test_binary_filelike(self):
        assert parse_json(io.BytesIO(b'[{"k": "v"}]')).sheets[0].row_count == 2

    def test_text_filelike(self):
        assert parse_json(io.StringIO('[{"k": "v"}]')).sheets[0].row_count == 2

    def test_path_input(self, tmp_path: Path):
        p = tmp_path / "x.json"
        p.write_text('[{"k": "v"}]', encoding="utf-8")
        assert parse_json(p).sheets[0].row_count == 2

    def test_path_string_input(self, tmp_path: Path):
        p = tmp_path / "x.json"
        p.write_text('[{"k": "v"}]', encoding="utf-8")
        # String containing only path-like chars (no '{' / '[') → treated as path
        assert parse_json(str(p)).sheets[0].row_count == 2

    def test_utf8_bom_stripped(self):
        text = '[{"name":"\u5f20\u4e09"}]'
        assert parse_json(text.encode("utf-8-sig")).sheets[0].rows[1].cells[0].value == "张三"


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


class TestFailures:
    def test_malformed_json_raises_corrupt(self):
        with pytest.raises(CorruptSourceError):
            parse_json("not valid json")

    @pytest.mark.parametrize("payload", ["true", "42", '"plain string"'])
    def test_unsupported_top_level_type_raises(self, payload):
        with pytest.raises(CorruptSourceError, match="must be an object or an array"):
            parse_json(payload)

    def test_unknown_timezone_raises(self):
        with pytest.raises(StructuredParseError):
            parse_json('[{"k": "v"}]', timezone_name="Not/A_Real_Zone")


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestWorkbookMetadata:
    def test_metadata_recorded(self):
        result = parse_json(
            '[{"k": "v"}]',
            source_filename="x.json",
            source_mime_type="application/json",
        )
        assert result.parser_version == PARSER_VERSION
        assert result.source_filename == "x.json"
        assert result.source_mime_type == "application/json"
        assert result.timezone == "Asia/Shanghai"
        assert result.sheets[0].merged_ranges == []
        assert result.sheets[0].name == "json"
