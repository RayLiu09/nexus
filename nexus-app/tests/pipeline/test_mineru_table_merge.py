"""Defect #3 — cross-page table merge + empty-table cleanup.

Locks in:
  - Consecutive table blocks where the anchor has a caption and subsequent
    pages do not are merged into a single logical block.
  - Image URIs, bboxes, and content from continuations roll up into the
    anchor; a ``page_range`` field marks the span.
  - A merged block that has only an image and no text content is stamped
    ``parse_quality = "image_only"`` so downstream chunkers can route it.
  - Fully empty table blocks (no caption, image, or content) are dropped.
  - "|  |" pipe-only rows are stripped from any table's content, even when
    no merge happens.

See docs/document_normalize_defects.md §缺陷 3.
"""
from __future__ import annotations

from nexus_app.pipeline.mineru_converter import (
    _merge_cross_page_tables,
    _strip_empty_table_rows,
)


def _table(
    *,
    block_id: str,
    page: int,
    bbox: list[int],
    caption: str = "",
    content: str = "",
    image_uris: dict[str, str] | None = None,
) -> dict:
    return {
        "block_id": block_id,
        "block_type": "table",
        "seq_no": int(block_id.split("-")[-1]),
        "page": page,
        "bbox": list(bbox),
        "caption": caption,
        "image_uris": dict(image_uris or {}),
        "source_locator": {"page": page, "bbox": list(bbox)},
        **({"content": content} if content else {}),
    }


def _paragraph(block_id: str, page: int, text: str) -> dict:
    return {
        "block_id": block_id,
        "block_type": "paragraph",
        "seq_no": int(block_id.split("-")[-1]),
        "page": page,
        "bbox": [10, 10, 100, 30],
        "text": text,
        "source_locator": {"page": page, "bbox": [10, 10, 100, 30]},
    }


def test_strip_empty_table_rows_keeps_real_rows():
    md = "| A | B |\n|  |  |\n| 1 | 2 |\n|   |   |\n| 3 | 4 |"
    out = _strip_empty_table_rows(md)
    assert out == "| A | B |\n| 1 | 2 |\n| 3 | 4 |"


def test_strip_empty_table_rows_noop_when_no_table_markup():
    assert _strip_empty_table_rows("plain text") == "plain text"
    assert _strip_empty_table_rows("") == ""


def test_cross_page_table_merge_collapses_continuations():
    blocks = [
        _table(
            block_id="block-p50-166",
            page=50,
            bbox=[82, 234, 510, 723],
            caption="表 3-1 直播电商相关政策一览表",
            content="| 时间 | 部门 | 文件 |\n| 2025.12 | 监管总局 | 网络交易办法 |",
            image_uris={"tbl_p50.jpg": "s3://x/tbl_p50.jpg"},
        ),
        _table(block_id="block-p51-167", page=51, bbox=[82, 115, 510, 712]),
        _table(block_id="block-p52-168", page=52, bbox=[82, 115, 511, 712]),
        _table(block_id="block-p53-169", page=53, bbox=[82, 115, 510, 712]),
        _table(block_id="block-p54-170", page=54, bbox=[82, 115, 510, 712]),
        _table(block_id="block-p55-171", page=55, bbox=[82, 115, 510, 712]),
        _paragraph("block-p56-172", 56, "下一节正文。"),
    ]
    md_parts = [
        "**表 3-1 直播电商相关政策一览表**\n\n| 时间 | 部门 | 文件 |\n| 2025.12 | 监管总局 | 网络交易办法 |",
        "",
        "",
        "",
        "",
        "",
        "下一节正文。",
    ]
    merged_blocks, merged_parts = _merge_cross_page_tables(blocks, md_parts)

    # 6 table blocks collapse into 1; paragraph survives → 2 total.
    table_blocks = [b for b in merged_blocks if b.get("block_type") == "table"]
    assert len(table_blocks) == 1
    assert len(merged_blocks) == 2

    anchor = table_blocks[0]
    assert anchor["caption"].startswith("表 3-1")
    # bbox bottom extends to cover continuations (last page bbox bottom = 712).
    assert anchor["bbox"][3] >= 712
    # page_range recorded.
    assert anchor.get("page_range") == [50, 55]
    # 1:1 lockstep preserved.
    assert len(merged_blocks) == len(merged_parts)
    # Anchor md_part regenerated from the (cleaned) fields.
    assert merged_parts[0].startswith("**表 3-1")
    assert "2025.12" in merged_parts[0]


def test_image_only_merged_table_gets_parse_quality_flag():
    blocks = [
        _table(
            block_id="block-p10-001",
            page=10,
            bbox=[82, 100, 510, 700],
            caption="表 X 仅有截图的多页表",
            image_uris={"x.jpg": "s3://x/x.jpg"},
        ),
        _table(block_id="block-p11-002", page=11, bbox=[82, 100, 510, 700]),
    ]
    md_parts = ["**表 X 仅有截图的多页表**", ""]
    out_blocks, _ = _merge_cross_page_tables(blocks, md_parts)
    assert len(out_blocks) == 1
    assert out_blocks[0].get("parse_quality") == "image_only"


def test_fully_empty_table_block_is_dropped():
    blocks = [
        _paragraph("block-p01-001", 1, "前段。"),
        _table(block_id="block-p01-002", page=1, bbox=[0, 0, 0, 0]),
        _paragraph("block-p01-003", 1, "后段。"),
    ]
    md_parts = ["前段。", "", "后段。"]
    out_blocks, out_parts = _merge_cross_page_tables(blocks, md_parts)
    assert [b["block_id"] for b in out_blocks] == ["block-p01-001", "block-p01-003"]
    assert out_parts == ["前段。", "后段。"]


def test_solitary_table_still_gets_empty_rows_stripped():
    blocks = [
        _table(
            block_id="block-p01-001",
            page=1,
            bbox=[82, 100, 510, 700],
            caption="表 A",
            content="| 列 |\n|  |\n| 值 |",
        ),
    ]
    md_parts = ["**表 A**\n\n| 列 |\n|  |\n| 值 |"]
    out_blocks, out_parts = _merge_cross_page_tables(blocks, md_parts)
    assert out_blocks[0]["content"] == "| 列 |\n| 值 |"
    assert "|  |" not in out_parts[0]
