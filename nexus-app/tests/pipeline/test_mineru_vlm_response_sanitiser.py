"""§9 P1 — _sanitise_vlm_table_response: strip LLM long-tail prose.

LLMs (especially Chinese vision models in helpful-assistant mode) ignore
"return only a markdown table" prompts and emit a chatty preamble or
postamble despite explicit forbidden-phrase lists. Examples observed in
production on the policy-table rescue:

  "当然可以。以下是您提供的表格内容..." (preamble)
  "说明：表格共 5 列..." (postamble)
  "若需导出为 CSV、Markdown 或 Excel 格式，可进一步转换。"
  "如需我为您生成 Markdown 表格、CSV 数据或可视化图表，请告知。"

Per docs/document_normalize_defects.md §9.5(B), the sanitiser must keep
ONLY pipe-bordered lines (table rows + GFM separator), discarding
everything before the first pipe row, after the last, and any in-between
non-pipe lines.

The sentinel "-" (model's "image is empty" response) is preserved
verbatim so the caller can distinguish "rescue failed" from "image
genuinely empty".
"""
from __future__ import annotations

from nexus_app.pipeline.mineru_converter import _sanitise_vlm_table_response


def test_returns_empty_for_none_or_empty():
    assert _sanitise_vlm_table_response(None) == ""
    assert _sanitise_vlm_table_response("") == ""
    assert _sanitise_vlm_table_response("   \n   \n") == ""


def test_dash_sentinel_preserved():
    assert _sanitise_vlm_table_response("-") == "-"
    assert _sanitise_vlm_table_response("  -  ") == "-"


def test_chatty_preamble_is_stripped():
    raw = (
        "当然可以。以下是您提供的表格内容：\n"
        "\n"
        "| 时间 | 部门 |\n"
        "| --- | --- |\n"
        "| 2020.11 | 监管总局 |\n"
    )
    out = _sanitise_vlm_table_response(raw)
    assert out == "| 时间 | 部门 |\n| --- | --- |\n| 2020.11 | 监管总局 |"


def test_chatty_postamble_is_stripped():
    raw = (
        "| 时间 | 部门 |\n"
        "| --- | --- |\n"
        "| 2020.11 | 监管总局 |\n"
        "| 2025.12 | 网信办 |\n"
        "\n"
        "说明：表格共 2 列，包含 2 行数据。\n"
        "若需导出为 CSV、Markdown 或 Excel 格式，可进一步转换。\n"
        "如需我为您生成 Markdown 表格，请告知。\n"
    )
    out = _sanitise_vlm_table_response(raw)
    assert out == (
        "| 时间 | 部门 |\n"
        "| --- | --- |\n"
        "| 2020.11 | 监管总局 |\n"
        "| 2025.12 | 网信办 |"
    )


def test_preamble_and_postamble_both_stripped():
    raw = (
        "Sure! Here is the table:\n\n"
        "| A | B |\n"
        "| --- | --- |\n"
        "| 1 | 2 |\n"
        "\n"
        "Let me know if you need anything else.\n"
    )
    out = _sanitise_vlm_table_response(raw)
    assert out == "| A | B |\n| --- | --- |\n| 1 | 2 |"


def test_non_pipe_lines_between_rows_are_dropped():
    """Some models inject explanatory lines between the header and data rows.
    Keep the rows, drop the noise."""
    raw = (
        "| A | B |\n"
        "| --- | --- |\n"
        "（以下是数据）\n"
        "| 1 | 2 |\n"
        "| 3 | 4 |\n"
    )
    out = _sanitise_vlm_table_response(raw)
    assert out == "| A | B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |"


def test_no_pipe_lines_returns_empty():
    raw = "I cannot read this image. Please try a clearer screenshot."
    out = _sanitise_vlm_table_response(raw)
    assert out == ""


def test_trailing_whitespace_in_pipe_rows_is_tolerated():
    raw = "   | A | B |   \n   | --- | --- |\n  | x | y |   \n"
    out = _sanitise_vlm_table_response(raw)
    assert out == "| A | B |\n| --- | --- |\n| x | y |"
