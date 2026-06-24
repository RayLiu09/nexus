"""Pipeline B `structured_parse` stage — format-specific parsers that produce a
canonical intermediate representation for downstream `profile_detect` and
`domain_normalize` consumers.

Scope:
  - B1.2 — xlsx parser
  - B1.4 — csv parser (worker-integrated), json parser (helper only;
    worker integration deferred to keep the existing `_load_record_payload`
    JSON path stable for crawler / database / webhook ingestion contracts)
  - B1.4+ — crawler-payload-specific shapes land per-source on demand

Public surface intentionally narrow — callers should import from this package,
not from format-specific submodules, so we can later swap implementations
(e.g. polars-backed xlsx reader) without breaking call sites.
"""
from __future__ import annotations

from nexus_app.structured_parse.csv_parser import parse_csv
from nexus_app.structured_parse.exceptions import (
    CorruptSourceError,
    EmptySourceError,
    StructuredParseError,
    UnsupportedFormatError,
)
from nexus_app.structured_parse.json_parser import parse_json
from nexus_app.structured_parse.schemas import (
    ParsedCell,
    ParsedRow,
    ParsedSheet,
    ParsedWorkbook,
)
from nexus_app.structured_parse.xlsx_parser import PARSER_VERSION, parse_xlsx

__all__ = [
    "PARSER_VERSION",
    "parse_xlsx",
    "parse_csv",
    "parse_json",
    "ParsedCell",
    "ParsedRow",
    "ParsedSheet",
    "ParsedWorkbook",
    "StructuredParseError",
    "CorruptSourceError",
    "EmptySourceError",
    "UnsupportedFormatError",
]
