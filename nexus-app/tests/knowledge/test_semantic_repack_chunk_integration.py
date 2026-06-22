"""Integration coverage for semantic_repack units -> KnowledgeChunk rows."""
from __future__ import annotations

from types import SimpleNamespace

from nexus_app.knowledge.router import route_and_chunk


def _kt_config() -> SimpleNamespace:
    return SimpleNamespace(
        chunking_config={},
        chunking_mode="passthrough_to_ragflow",
        chunking_strategy="semantic",
        source_kind="extracted_from_normalized",
        ragflow={"chunk_method": "naive"},
        max_chunks_per_unit=20,
    )


def test_atomic_table_rows_become_semantic_chunks_with_row_locator_and_metadata():
    md = """| 发布时间 | 部门 | 文件名 | 内容摘要 |
| --- | --- | --- | --- |
| 2021.04 | 国家网信办等七部门 | 《网络直播营销管理办法》 | 平台应建立审核机制 |
| 2022.03 | 市场监管总局 | 《网络交易监管办法》 | 强化平台责任 |"""
    blocks = [
        {
            "block_id": "h-1",
            "block_type": "heading",
            "seq_no": 1,
            "page": 50,
            "bbox": [0, 0, 100, 20],
            "text": "第三章 政策治理",
            "heading_level": 1,
            "md_char_range": None,
        },
        {
            "block_id": "tbl-1",
            "block_type": "table",
            "seq_no": 2,
            "page": 50,
            "bbox": [10, 20, 500, 700],
            "caption": "表 3-1 政策一览",
            "content": md,
            "md_char_range": [0, len(md)],
        },
    ]

    chunks = route_and_chunk(
        md,
        {"code": "industry_research_kb", "co_emission_origin": None},
        _kt_config(),
        "ref-1",
        content_blocks=blocks,
    )

    table_rows = [c for c in chunks if c.chunk_metadata.get("anchor_role") == "table_row"]
    assert len(table_rows) == 2
    first = table_rows[0]
    assert first.chunk_metadata["table_parent_block_id"] == "tbl-1"
    assert first.chunk_metadata["table_row_index"] == 1
    assert first.chunk_metadata["table_columns"] == ["发布时间", "部门", "文件名", "内容摘要"]
    assert first.chunk_metadata["locator_precision"] == "markdown_row"
    assert "发布时间: 2021.04" in first.content
    assert first.source_block_ids == ["tbl-1"]
    assert first.locator["heading_path"] == [{"level": 1, "title": "第三章 政策治理"}]
    assert first.locator["md_char_range"][0] == md.index("| 2021.04")
    assert first.locator["blocks"][0]["md_char_range"] == first.locator["md_char_range"]
