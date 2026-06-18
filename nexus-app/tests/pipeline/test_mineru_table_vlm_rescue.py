"""Defect #3 extension — VLM rescue for degraded MinerU tables.

MinerU pipeline mode periodically emits a table whose HTML carries a header
row but only empty pipe-only data rows (the cross-page anchor case observed
on 表 3-1 直播电商相关政策一览表). After empty-row stripping the markdown is
useless. When a cropped image is available AND an image_analyzer is wired,
the converter must now invoke VLM with the table prompt and adopt its output
as the canonical table_md, tagging the block with parse_quality="vlm_rescue".

Useful tables must NOT trigger the rescue (extra VLM call is waste).

See docs/document_normalize_defects.md §缺陷 3.
"""
from __future__ import annotations

from nexus_app.pipeline.mineru_converter import (
    _table_md_is_useful,
    convert,
)


def test_useful_table_md_passes_check():
    md = "| 时间 | 部门 | 文件 |\n| 2025.12 | 监管总局 | 网络交易办法 |"
    assert _table_md_is_useful(md) is True


def test_header_only_table_md_is_not_useful():
    md = "| 时间 | 部门 | 文件 |"
    assert _table_md_is_useful(md) is False


def test_empty_or_none_table_md_is_not_useful():
    assert _table_md_is_useful(None) is False
    assert _table_md_is_useful("") is False


def test_table_with_separator_row_only_is_not_useful():
    md = "| h1 | h2 |\n|---|---|"
    # one content row (header) + a separator → only the header counts as
    # content; needs at least header + data → False.
    assert _table_md_is_useful(md) is False


# ---------------------------------------------------------------------------
# Integration: convert() routes degraded tables to VLM.
# ---------------------------------------------------------------------------

class _TableVLMAnalyzer:
    """Returns a deterministic markdown table so the test can assert that
    convert() promoted the VLM output to table_md."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def analyze(self, _image_bytes: bytes, btype: str, caption: str) -> str:
        self.calls.append((btype, caption))
        return (
            "| 时间 | 部门 | 文件 | 主要内容 |\n"
            "| 2020.11 | 国务院 | 关于 X 的指导意见 | 概述。 |\n"
            "| 2021.05 | 市场监管 | 网络交易办法 | 完整规则。 |\n"
            "| 2025.12 | 网信办 | 平台规则监督管理办法 | 平台义务。 |"
        )


class _Storage:
    def get_bytes(self, _key: str) -> bytes:
        return b"\x00" * 8


def _degraded_table_block(image_path: str) -> dict:
    """Mimic MinerU pipeline output: caption + table_body with HTML that has
    a header row and a bunch of empty body rows."""
    empty_rows = "\n".join("<tr><td></td><td></td><td></td></tr>" for _ in range(20))
    html = (
        "<table><tr><th>时间</th><th>部门</th><th>文件</th></tr>"
        + empty_rows
        + "</table>"
    )
    return {
        "type": "table",
        "bbox": [82, 234, 510, 723],
        "blocks": [
            {
                "type": "table_caption",
                "lines": [{"spans": [{"type": "text", "content": "表 3-1 …直播电商相关政策一览表"}]}],
            },
            {
                "type": "table_body",
                "lines": [{"spans": [{"type": "table", "html": html, "image_path": image_path}]}],
            },
        ],
    }


def _useful_table_block(image_path: str) -> dict:
    html = (
        "<table>"
        "<tr><th>列A</th><th>列B</th></tr>"
        "<tr><td>1</td><td>2</td></tr>"
        "<tr><td>3</td><td>4</td></tr>"
        "</table>"
    )
    return {
        "type": "table",
        "bbox": [82, 234, 510, 500],
        "blocks": [
            {
                "type": "table_caption",
                "lines": [{"spans": [{"type": "text", "content": "表 X 简单表"}]}],
            },
            {
                "type": "table_body",
                "lines": [{"spans": [{"type": "table", "html": html, "image_path": image_path}]}],
            },
        ],
    }


def test_degraded_table_triggers_vlm_rescue():
    pdf_info = [{"page_idx": 50, "para_blocks": [_degraded_table_block("tbl_p50.jpg")]}]
    analyzer = _TableVLMAnalyzer()
    blocks, md, _toc = convert(
        pdf_info,
        image_uris={"tbl_p50.jpg": "s3://x/tbl_p50.jpg"},
        image_analyzer=analyzer,
        storage=_Storage(),
    )
    # VLM was invoked once with the table prompt.
    assert analyzer.calls == [("table", "表 3-1 …直播电商相关政策一览表")]
    table_blocks = [b for b in blocks if b.get("block_type") == "table"]
    assert len(table_blocks) == 1
    rescued = table_blocks[0]
    assert rescued.get("parse_quality") == "vlm_rescue"
    # Content reflects the VLM-rescued table, not the degraded MinerU HTML.
    assert "2020.11" in rescued["content"]
    assert "2025.12" in rescued["content"]
    # body_markdown carries the rescued data too.
    assert "2025.12" in md
    # No empty pipe rows survived.
    for line in md.splitlines():
        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            assert any(cells), f"empty pipe row leaked: {line!r}"


def test_useful_table_does_not_trigger_vlm():
    pdf_info = [{"page_idx": 10, "para_blocks": [_useful_table_block("tbl_p10.jpg")]}]
    analyzer = _TableVLMAnalyzer()
    blocks, _md, _toc = convert(
        pdf_info,
        image_uris={"tbl_p10.jpg": "s3://x/tbl_p10.jpg"},
        image_analyzer=analyzer,
        storage=_Storage(),
    )
    assert analyzer.calls == [], "VLM must not run for tables MinerU parsed cleanly"
    table_blocks = [b for b in blocks if b.get("block_type") == "table"]
    assert table_blocks[0].get("parse_quality") is None  # no rescue tag
    assert "1" in table_blocks[0]["content"]
