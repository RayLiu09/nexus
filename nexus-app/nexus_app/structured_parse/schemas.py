"""Canonical intermediate representation produced by `structured_parse` parsers.

Downstream consumers (`profile_detect`, `domain_normalize`) MUST operate on
this shape rather than re-opening the source bytes — this keeps the parser
as the single point that handles merged-cell forward-fill, datetime
normalization, index-column drop, etc. (per contract-freeze §3.4 / §5.0).
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# Possible cell value types after normalization. Datetimes are carried as
# ISO8601 strings (see `xlsx_parser._normalize_value`); the str / int / float /
# bool / None cases are the openpyxl-native types passed through unchanged.
CellValue = str | int | float | bool | None


class ParsedCell(BaseModel):
    """A single cell with provenance for downstream trace records.

    `column` and `column_letter` are kept as redundant pairs so callers can
    use either numeric or excel-style addressing without re-deriving.
    `is_merged_origin` + `is_filled_from_merge` are mutually exclusive: a cell
    is either the origin of a merged range, or filled from one, or neither.
    `merged_range` is present on both origin and filled cells.
    """
    column: int                          # 1-based column index
    column_letter: str                   # excel-style ('A', 'B', ..., 'AA')
    value: CellValue                     # normalized (datetime → ISO8601 string)
    raw_text: str | None = None          # original repr when value was normalized away from openpyxl native type
    is_merged_origin: bool = False       # True if this cell is the top-left of a merged range
    is_filled_from_merge: bool = False   # True if value was forward-filled from a merged origin
    merged_range: str | None = None      # e.g. "A5:A20" — present on both origin and filled cells
    is_multiline: bool = False           # raw text contains '\n' or '\r' (preserved verbatim)


class ParsedRow(BaseModel):
    """A row in original sheet order. `row_index` is sheet-absolute and is
    NOT renumbered when columns are dropped (so trace audits still match).
    """
    row_index: int                       # 1-based row index
    cells: list[ParsedCell] = Field(default_factory=list)
    is_placeholder_candidate: bool = False  # any cell text matches placeholder patterns (e.g. "……")
    is_empty: bool = False                  # all cells are None / empty string


class ParsedSheet(BaseModel):
    """A sheet, preserving original name + workbook position + merged ranges."""
    name: str
    sheet_index: int                     # 0-based, matches workbook.sheetnames order
    rows: list[ParsedRow] = Field(default_factory=list)
    merged_ranges: list[str] = Field(default_factory=list)  # sorted for determinism
    column_count: int = 0                # max column observed (pre-drop)
    row_count: int = 0                   # max row observed
    dropped_index_columns: list[int] = Field(default_factory=list)  # 1-based, sorted


class ParsedWorkbook(BaseModel):
    """Top-level intermediate representation. Returned by `parse_xlsx()` (B1.2)
    and (later) `parse_csv()` / `parse_json()` (B1.4).
    """
    parser_version: str                  # e.g. "xlsx_parser.v1"
    parsed_at: datetime                  # wall-clock at parse time, tz-aware (UTC)
    source_filename: str | None = None
    source_mime_type: str | None = None
    timezone: str                        # IANA name used to attach to naive cell datetimes
    sheets: list[ParsedSheet] = Field(default_factory=list)

    def get_sheet(self, name: str) -> ParsedSheet | None:
        """Look up a sheet by name (None if missing)."""
        for s in self.sheets:
            if s.name == name:
                return s
        return None
