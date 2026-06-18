"""§9 P0 — _table_html_to_markdown must accept attribute-decorated tags.

Background (docs/document_normalize_defects.md §9):
  - MinerU pipeline mode always emits <tr>/<td> with colspan + rowspan
    attributes (even when value is 1). The prior regex matched only bare
    <tr>/<td>, dropping 99.6% of cell content on real documents — what we
    misdiagnosed as "MinerU lost the data" for cross-page tables.
  - This module locks in the corrected parser: attributes accepted, <th>
    accepted, colspan/rowspan handled, inline <br> flattened, pipe and
    backslash escaped inside cells.
"""
from __future__ import annotations

from nexus_app.pipeline.mineru_converter import (
    _cell_attr_int,
    _normalise_cell_text,
    _table_html_to_markdown,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_cell_attr_int_defaults_to_one():
    assert _cell_attr_int("", "colspan") == 1
    assert _cell_attr_int('class="x"', "colspan") == 1


def test_cell_attr_int_reads_quoted_and_unquoted():
    assert _cell_attr_int('colspan="3" rowspan="2"', "colspan") == 3
    assert _cell_attr_int('colspan="3" rowspan="2"', "rowspan") == 2
    assert _cell_attr_int("colspan=4 class='x'", "colspan") == 4
    # Never below 1.
    assert _cell_attr_int('colspan="0"', "colspan") == 1
    # Garbage falls back.
    assert _cell_attr_int('colspan="abc"', "colspan") == 1


def test_normalise_cell_text_flattens_inline_html_and_escapes_pipes():
    assert _normalise_cell_text("hello") == "hello"
    assert _normalise_cell_text("line1<br>line2") == "line1 line2"
    assert _normalise_cell_text("line1<br/>line2<br />line3") == "line1 line2 line3"
    assert _normalise_cell_text("<p>wrapped</p>") == "wrapped"
    assert _normalise_cell_text("a | b") == r"a \| b"
    assert _normalise_cell_text(r"path\sub") == r"path\\sub"
    # Whitespace collapsed.
    assert _normalise_cell_text("  a   b\n c\t") == "a b c"


# ---------------------------------------------------------------------------
# Cell with attributes — the P0 regression
# ---------------------------------------------------------------------------

def test_minerU_style_attributed_cells_are_parsed():
    html = (
        '<table>'
        '<tr><td colspan="1" rowspan="1">时间</td>'
        '    <td colspan="1" rowspan="1">部门</td></tr>'
        '<tr><td colspan="1" rowspan="1">2020.11</td>'
        '    <td colspan="1" rowspan="1">市场监管总局</td></tr>'
        '<tr><td colspan="1" rowspan="1">2021.05</td>'
        '    <td colspan="1" rowspan="1">网信办</td></tr>'
        '</table>'
    )
    out = _table_html_to_markdown(html)
    lines = out.splitlines()
    assert lines[0] == "| 时间 | 部门 |"
    assert lines[1] == "| --- | --- |"
    assert lines[2] == "| 2020.11 | 市场监管总局 |"
    assert lines[3] == "| 2021.05 | 网信办 |"


def test_th_cells_supported():
    html = (
        '<table>'
        '<tr><th>列A</th><th>列B</th></tr>'
        '<tr><td>1</td><td>2</td></tr>'
        '</table>'
    )
    out = _table_html_to_markdown(html)
    assert out.splitlines()[0] == "| 列A | 列B |"
    assert out.splitlines()[1] == "| --- | --- |"
    assert out.splitlines()[2] == "| 1 | 2 |"


# ---------------------------------------------------------------------------
# colspan / rowspan
# ---------------------------------------------------------------------------

def test_colspan_duplicates_cell_text_to_keep_grid_width():
    # First row header spans both columns; second row has two cells.
    html = (
        '<table>'
        '<tr><td colspan="2">合并标题</td></tr>'
        '<tr><td>A</td><td>B</td></tr>'
        '</table>'
    )
    out = _table_html_to_markdown(html)
    lines = out.splitlines()
    # Header row is widened to 2 columns by duplicating the merged text.
    assert lines[0] == "| 合并标题 | 合并标题 |"
    assert lines[1] == "| --- | --- |"
    assert lines[2] == "| A | B |"


def test_rowspan_propagates_value_into_subsequent_rows():
    # First column rowspan=2 → second row inherits the value in column 0.
    html = (
        '<table>'
        '<tr><td rowspan="2">同类</td><td>A</td></tr>'
        '<tr><td>B</td></tr>'
        '</table>'
    )
    out = _table_html_to_markdown(html)
    lines = out.splitlines()
    assert lines[0] == "| 同类 | A |"
    assert lines[1] == "| --- | --- |"
    # Row 2 only declared 1 <td> (the B); rowspan from row 1 fills col 0.
    assert lines[2] == "| 同类 | B |"


def test_mixed_rowspan_and_colspan_keeps_grid_consistent():
    html = (
        '<table>'
        '<tr><th rowspan="2">维度</th><th>阶段1</th><th>阶段2</th></tr>'
        '<tr><td>v1</td><td>v2</td></tr>'
        '<tr><td colspan="3">合并底部</td></tr>'
        '</table>'
    )
    out = _table_html_to_markdown(html)
    lines = out.splitlines()
    assert lines[0] == "| 维度 | 阶段1 | 阶段2 |"
    assert lines[1] == "| --- | --- | --- |"
    assert lines[2] == "| 维度 | v1 | v2 |"
    assert lines[3] == "| 合并底部 | 合并底部 | 合并底部 |"


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------

def test_empty_or_no_rows_returns_empty_string():
    assert _table_html_to_markdown("") == ""
    assert _table_html_to_markdown("<table></table>") == ""
    # Row exists but cells are missing (very rare malformed case).
    assert _table_html_to_markdown("<table><tr></tr></table>") == ""


def test_html_entities_decoded():
    html = '<table><tr><td>&quot;A&amp;B&quot;</td><td>&lt;x&gt;</td></tr></table>'
    out = _table_html_to_markdown(html)
    assert out.splitlines()[0] == '| "A&B" | <x> |'


def test_inline_equation_preserved_as_dollar_math():
    html = '<table><tr><td>velocity</td><td><eq>v = d/t</eq></td></tr></table>'
    out = _table_html_to_markdown(html)
    assert out.splitlines()[0] == "| velocity | $v = d/t$ |"


def test_real_minerU_policy_table_excerpt_yields_real_rows():
    """Mirrors the production HTML shape captured on sample asset
    4abe6b71… (policy table anchor on page 50). Every <td> has the
    colspan/rowspan attributes that the old regex rejected."""
    html = (
        '<table>'
        '<tr><td colspan="1" rowspan="1">发布时间</td>'
        '<td colspan="1" rowspan="1">部门</td>'
        '<td colspan="1" rowspan="1">名称</td>'
        '<td colspan="1" rowspan="1">直播电商相关内容</td></tr>'
        '<tr><td colspan="1" rowspan="1">2020.11</td>'
        '<td colspan="1" rowspan="1">市场监管总局</td>'
        '<td colspan="1" rowspan="1">《关于加强网络直播营销活动监管的指导意见》</td>'
        '<td colspan="1" rowspan="1">压实主体责任…</td></tr>'
        '<tr><td colspan="1" rowspan="1">2025.12</td>'
        '<td colspan="1" rowspan="1">市场监管总局、国家网信办</td>'
        '<td colspan="1" rowspan="1">《直播电商监督管理办法》</td>'
        '<td colspan="1" rowspan="1">强化监督管理手段…</td></tr>'
        '</table>'
    )
    out = _table_html_to_markdown(html)
    # Real data must come through, no empty | | rows.
    assert "2020.11" in out
    assert "市场监管总局" in out
    assert "2025.12" in out
    assert "《直播电商监督管理办法》" in out
    # No pipe-only empty row anywhere.
    for line in out.splitlines():
        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            assert any(cells), f"empty pipe-only row leaked: {line!r}"
