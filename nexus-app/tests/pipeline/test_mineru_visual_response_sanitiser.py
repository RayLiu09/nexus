"""§11 — image/chart VLM response sanitiser and chart→table re-route.

Background (docs/document_normalize_defects.md §11): the chart prompt
historically asked the model for "Chart Type:", "Axis Labels:", "Legend:",
"Key Data Values:", "Trend:" structured output. Users complained that this
itself was noise — they want "the model to directly answer the image
content without irrelevant info".

Two layers of fix:
  A. New §11-A prompts (tested separately) forbid those meta-labels.
  B. _sanitise_vlm_visual_response strips them as a safety net when the
     model emits them anyway.
  C. _looks_tabular detects chart blocks that are actually tables;
     _handle_visual re-prompts with the table contract.

This module tests B + C; the prompt changes (A) are implicitly exercised
by the integration test that runs convert() against a fake analyser.
"""
from __future__ import annotations

from nexus_app.pipeline.mineru_converter import (
    _looks_tabular,
    _sanitise_vlm_visual_response,
    convert,
)


# ---------------------------------------------------------------------------
# §11-B: _sanitise_vlm_visual_response
# ---------------------------------------------------------------------------

def test_sanitiser_passthrough_for_clean_content():
    raw = "X 年份 2019-2024, Y 增速 0-60%\n\n| 年份 | 增速 |\n| --- | --- |\n| 2020 | 41.4% |"
    out = _sanitise_vlm_visual_response(raw)
    # The substantive content survives intact.
    assert "2020" in out
    assert "41.4%" in out
    assert "X 年份" in out


def test_sanitiser_drops_pure_meta_label_lines():
    raw = (
        "Chart Type: Combined bar-line chart.\n"
        "Axis Labels:\n"
        "Legend Entries:\n"
        "Key Data Values:\n"
        "- 2020: 41.4%\n"
        "- 2021: 19.6%\n"
        "Trend: Growth declines.\n"
        "Summary: Overall down.\n"
    )
    out = _sanitise_vlm_visual_response(raw)
    # Pure meta labels gone.
    assert "Axis Labels:" not in out
    assert "Legend Entries:" not in out
    assert "Key Data Values:" not in out
    assert "Trend:" not in out
    assert "Summary:" not in out
    # "Chart Type: Combined bar-line chart." line — the prefix gets
    # stripped but the trailing content stays.
    assert "Chart Type" not in out
    assert "Combined bar-line chart" in out
    # Substantive data survives.
    assert "2020: 41.4%" in out
    assert "2021: 19.6%" in out


def test_sanitiser_strips_label_prefix_but_keeps_inline_value():
    raw = (
        "X-axis: Years 2019–2024.\n"
        "Y-axis (left): Market size (billion yuan), range 0–60,000.\n"
        "- 2024: 45,146B.\n"
    )
    out = _sanitise_vlm_visual_response(raw)
    assert "X-axis:" not in out
    assert "Y-axis" not in out
    assert "Years 2019–2024." in out
    assert "Market size (billion yuan), range 0–60,000." in out
    assert "2024: 45,146B." in out


def test_sanitiser_drops_chatty_prologue():
    raw = (
        "Sure! Here is the chart description:\n"
        "- 2020: 100\n"
        "- 2021: 120\n"
    )
    out = _sanitise_vlm_visual_response(raw)
    assert "Sure" not in out
    assert "2020: 100" in out
    assert "2021: 120" in out


def test_sanitiser_keeps_dash_sentinel():
    assert _sanitise_vlm_visual_response("-") == "-"
    assert _sanitise_vlm_visual_response("  -  ") == "-"


def test_sanitiser_collapses_multiple_blank_lines():
    raw = "Line A\n\n\n\nLine B\n"
    out = _sanitise_vlm_visual_response(raw)
    # At most one blank line between content lines.
    assert "\n\n\n" not in out
    assert "Line A" in out and "Line B" in out


# ---------------------------------------------------------------------------
# §11-C: _looks_tabular detection
# ---------------------------------------------------------------------------

def test_looks_tabular_recognises_explicit_keywords_with_rows():
    text = (
        "Chart Type: Tabular comparison (4-column, 4-row matrix).\n"
        "Rows: 政策特征, 治理主体, 典型治理工具.\n"
        "Columns: Four stages..."
    )
    assert _looks_tabular(text) is True


def test_looks_tabular_recognises_pipe_table_inside_response():
    text = (
        "Chart Type: not specified.\n"
        "| col1 | col2 |\n"
        "| 1 | 2 |\n"
        "| 3 | 4 |\n"
    )
    assert _looks_tabular(text) is True


def test_looks_tabular_rejects_normal_chart_description():
    text = (
        "X-axis: Years 2019–2024.\n"
        "Y-axis: Market size.\n"
        "- 2020: 100\n"
        "- 2021: 120\n"
    )
    assert _looks_tabular(text) is False


def test_looks_tabular_handles_none_and_empty():
    assert _looks_tabular(None) is False
    assert _looks_tabular("") is False


# ---------------------------------------------------------------------------
# Integration: chart→table re-route through convert()
# ---------------------------------------------------------------------------

class _ChartIsActuallyTableAnalyzer:
    """Returns a 'Tabular comparison' description when called with chart
    prompt, then a proper markdown table when re-called with table prompt."""

    def __init__(self):
        self.calls: list[str] = []

    def analyze(self, _image_bytes: bytes, btype: str, _caption: str) -> str:
        self.calls.append(btype)
        if btype == "chart":
            return (
                "Chart Type: Tabular comparison (3-row, 4-col matrix).\n"
                "Axis Labels:\n"
                "- Rows: 政策特征, 治理主体, 典型治理工具\n"
                "- Columns: Stage1, Stage2, Stage3, Stage4\n"
                "Legend: None.\n"
                "Key Data Values:\n"
                "- Policy: A → B → C → D\n"
            )
        if btype == "table":
            return (
                "| 维度 | Stage1 | Stage2 | Stage3 | Stage4 |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| 政策特征 | A | B | C | D |\n"
                "| 治理主体 | a | b | c | d |\n"
                "| 典型治理工具 | i | ii | iii | iv |\n"
            )
        return "-"


def _chart_image_block(path: str):
    return {
        "type": "chart",
        "bbox": [10, 10, 600, 500],
        "blocks": [
            {"type": "image_body",
             "lines": [{"spans": [{"type": "chart", "image_path": path}]}]},
        ],
    }


class _Storage:
    def get_bytes(self, _key: str) -> bytes:
        return b"\x00" * 16


def test_chart_to_table_recovery_promotes_block_type():
    pdf_info = [{"page_idx": 73, "para_blocks": [_chart_image_block("x.jpg")]}]
    analyzer = _ChartIsActuallyTableAnalyzer()
    blocks, _md, _toc = convert(
        pdf_info, image_uris={"x.jpg": "s3://x/x.jpg"},
        image_analyzer=analyzer, storage=_Storage(),
    )
    # Both VLM calls happened: first chart, then table re-route.
    assert analyzer.calls == ["chart", "table"]
    # Block was promoted to type="table" with the recovered markdown.
    recovered = next(b for b in blocks if b.get("page") == 73)
    assert recovered.get("block_type") == "table"
    assert recovered.get("parse_quality") == "chart_to_table_recovered"
    assert "政策特征 | A | B | C | D" in recovered["content"]
    assert "Tabular comparison" not in recovered["content"]
    assert "Axis Labels" not in recovered["content"]


class _GenuineChartAnalyzer:
    """A non-tabular chart description that should NOT be re-routed."""

    def __init__(self):
        self.calls: list[str] = []

    def analyze(self, _image_bytes: bytes, btype: str, _caption: str) -> str:
        self.calls.append(btype)
        if btype == "chart":
            return (
                "X-axis: Years 2019–2024.\n"
                "Y-axis: Market size (billion).\n"
                "- 2020: 100\n"
                "- 2021: 120\n"
                "- 2022: 140\n"
                "Trend: monotonically increasing.\n"
            )
        return "should not be called"


def test_genuine_chart_is_not_rerouted_and_meta_labels_stripped():
    pdf_info = [{"page_idx": 15, "para_blocks": [_chart_image_block("c.jpg")]}]
    analyzer = _GenuineChartAnalyzer()
    blocks, md, _toc = convert(
        pdf_info, image_uris={"c.jpg": "s3://x/c.jpg"},
        image_analyzer=analyzer, storage=_Storage(),
    )
    # Only the initial chart call.
    assert analyzer.calls == ["chart"]
    chart = next(b for b in blocks if b.get("page") == 15)
    assert chart.get("block_type") == "chart"
    assert chart.get("parse_quality") != "chart_to_table_recovered"
    # Sanitiser stripped meta-labels but kept data.
    assert "X-axis:" not in chart["content"]
    assert "Y-axis:" not in chart["content"]
    assert "Trend:" not in chart["content"]
    assert "Years 2019–2024." in chart["content"]
    assert "Market size (billion)." in chart["content"]
    for needle in ("2020: 100", "2021: 120", "2022: 140"):
        assert needle in chart["content"]
    # And the body markdown shows the cleaned content, wrapped as blockquote.
    assert "X-axis:" not in md
    assert "Trend:" not in md
