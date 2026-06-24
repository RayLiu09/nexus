"""Module-local configuration constants for `structured_parse`.

These defaults live HERE (per implementation-plan decision 8) instead of in
`config/governance_rules.json`: they are parser-level technical concerns
(detecting row-number columns, recognizing placeholder cells, default
timezone), not business governance rules.

Callers (parsers, worker) MAY override per DataSource via explicit arguments
to `parse_xlsx()` / `parse_csv()` / etc.
"""
from __future__ import annotations

# Default IANA timezone used when a cell carries a naive datetime (Excel
# stores datetimes without timezone info). Downstream callers may override
# per DataSource via the `timezone_name` argument.
DEFAULT_TIMEZONE: str = "Asia/Shanghai"


# Column header aliases that indicate a pure row-number / index column.
# When the first row of a sheet has a cell value matching one of these
# (case-insensitive, whitespace-trimmed), the column is dropped from the
# parsed output to keep it from leaking into domain fields.
#
# Kept here (not in governance_rules.json) because this is a structural
# parsing concern, not a business rule. Adding new aliases is a parser-level
# config change, not a governance decision.
INDEX_COLUMN_ALIASES: frozenset[str] = frozenset({
    "序号", "编号", "row_id", "row id", "id", "no.", "no", "#",
})


# Cell text patterns that mark a row as a placeholder (e.g. "……" used by
# human authors to denote omitted records).
#
# Per design §3.4 we only FLAG rows here — actual filtering happens in
# domain_normalize / quality_validate so quality scoring can see the raw
# placeholder counts.
PLACEHOLDER_CELL_PATTERNS: frozenset[str] = frozenset({
    "……", "...", "省略", "示例", "example", "tbd",
})
