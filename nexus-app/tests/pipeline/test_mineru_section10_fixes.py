"""§10 — three fixes addressing duplicated section text on cross-page tables.

1. Multi-page table merge captures per-page bboxes so the rescue pass can
   crop each rendered PDF page to the table region — without that, VLM
   greedily packs neighbouring headings/paragraphs/footnotes into table
   rows (sample 4abe6b71… p55 mis-rendered "二、地方规范创新精准落地"
   heading + body paragraphs as 4-column padding rows).

2. VLM response sanitiser drops "padding rows": ≥3 columns with only 1
   non-empty cell. Belt-and-suspenders behind the bbox crop.

3. TOC extractor handles concatenated TOC blocks (MinerU sometimes flattens
   the entire table-of-contents into a single paragraph; the per-line run
   detector misses them).
"""
from __future__ import annotations

from nexus_app.pipeline.mineru_converter import (
    _classify_toc_concat_block,
    _is_padding_row,
    _merge_cross_page_tables,
    _sanitise_vlm_table_response,
    convert,
)


# ---------------------------------------------------------------------------
# Padding-row detection
# ---------------------------------------------------------------------------

def test_padding_row_detected_for_single_filled_cell_out_of_4():
    assert _is_padding_row("| 二、地方规范创新精准落地 |  |  |  |") is True
    assert _is_padding_row("| -47- |  |  |  |") is True


def test_padding_row_not_flagged_for_two_filled_cells():
    assert _is_padding_row("| 2025.12 | 监管总局 |  |  |") is False


def test_padding_row_not_flagged_for_two_column_table():
    # 2-col tables can legitimately have one empty cell on a continuation row.
    assert _is_padding_row("| 标题 |  |") is False


def test_padding_row_not_flagged_for_separator():
    assert _is_padding_row("| --- | --- | --- | --- |") is False


def test_sanitiser_drops_padding_rows_between_real_rows():
    raw = (
        "| 时间 | 部门 | 文件 | 内容 |\n"
        "| --- | --- | --- | --- |\n"
        "| 2025.12 | 监管总局 | A | x |\n"
        "| 二、地方规范创新精准落地 |  |  |  |\n"
        "| 除国家相关部门... |  |  |  |\n"
        "| 2025.12 | 网信办 | B | y |\n"
    )
    out = _sanitise_vlm_table_response(raw)
    assert "二、地方规范" not in out
    assert "除国家相关部门" not in out
    assert "2025.12 | 监管总局" in out
    assert "2025.12 | 网信办" in out


# ---------------------------------------------------------------------------
# per_page_bboxes captured during merge
# ---------------------------------------------------------------------------

def _table_block(*, block_id, page, bbox, caption="", content="", image_uris=None):
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


def test_merge_captures_per_page_bboxes():
    blocks = [
        _table_block(block_id="block-p50-001", page=50, bbox=[82, 234, 510, 723],
                     caption="表 X", content="| a | b |\n| --- | --- |\n| 1 | 2 |"),
        _table_block(block_id="block-p51-002", page=51, bbox=[82, 115, 510, 712]),
        _table_block(block_id="block-p55-003", page=52, bbox=[82, 114, 510, 281]),  # short
    ]
    md_parts = ["**表 X**\n\n| a | b |\n| --- | --- |\n| 1 | 2 |", "", ""]
    out_blocks, _ = _merge_cross_page_tables(blocks, md_parts)
    assert len(out_blocks) == 1
    merged = out_blocks[0]
    assert merged.get("page_range") == [50, 52]
    bboxes = merged.get("per_page_bboxes")
    assert bboxes is not None
    assert bboxes.get(50) == [82, 234, 510, 723]
    assert bboxes.get(51) == [82, 115, 510, 712]
    assert bboxes.get(52) == [82, 114, 510, 281]  # crucially preserved


# ---------------------------------------------------------------------------
# Renderer receives bbox argument during rescue
# ---------------------------------------------------------------------------

def test_rescue_passes_per_page_bbox_to_renderer():
    """Renderer must be called with the per-page bbox so it can crop the
    page image to the table region. Without bbox cropping the VLM pulls
    headings/paragraphs into the table grid."""
    pdf_info = [
        {"page_idx": 50, "para_blocks": [{
            "type": "table", "bbox": [82, 234, 510, 723],
            "blocks": [
                {"type": "table_caption",
                 "lines": [{"spans": [{"type": "text", "content": "表 X 政策一览表"}]}]},
                {"type": "table_body",
                 "lines": [{"spans": [{"type": "table",
                                       "html": ("<table><tr><th>时间</th><th>内容</th></tr>"
                                                "<tr><td>2020.11</td><td>OLD</td></tr></table>"),
                                       "image_path": "a.jpg"}]}]},
            ],
        }]},
        {"page_idx": 51, "para_blocks": [{
            "type": "table", "bbox": [82, 115, 510, 712],
            "blocks": [{"type": "table_body", "lines": []}],
        }]},
        {"page_idx": 52, "para_blocks": [{
            "type": "table", "bbox": [82, 114, 510, 281],  # short — table really ends here
            "blocks": [{"type": "table_body", "lines": []}],
        }]},
    ]
    bbox_calls: list[tuple[int, list | None]] = []

    def renderer(page_idx, bbox=None):
        bbox_calls.append((page_idx, list(bbox) if bbox else None))
        # Return distinct bytes so analyzer can map per page.
        return f"PAGE{page_idx}".encode()

    class Analyzer:
        def analyze(self, image_bytes, btype, caption):
            payload = {
                b"PAGE51": "| 时间 | 内容 |\n| --- | --- |\n| 2021.05 | B |",
                b"PAGE52": "| 时间 | 内容 |\n| --- | --- |\n| 2025.12 | C |",
            }
            return payload.get(image_bytes, "-")

    out_blocks, _md, _toc = convert(
        pdf_info, image_uris={"a.jpg": "s3://x/a.jpg"},
        image_analyzer=Analyzer(), storage=None, pdf_renderer=renderer,
    )
    # Renderer was called once per CONTINUATION page (51, 52) — not 50.
    assert [c[0] for c in bbox_calls] == [51, 52]
    # bbox passed reflects the page-specific table area.
    bbox_by_page = {pid: bb for pid, bb in bbox_calls}
    assert bbox_by_page[51] == [82, 115, 510, 712]
    assert bbox_by_page[52] == [82, 114, 510, 281]
    # Merged table content preserved anchor + continuation rows.
    table = next(b for b in out_blocks if b.get("block_type") == "table")
    for needle in ("OLD", "2021.05", "2025.12"):
        assert needle in table["content"]


# ---------------------------------------------------------------------------
# Concatenated TOC block detection
# ---------------------------------------------------------------------------

def test_concat_toc_block_with_many_fragments_is_recognised():
    text = (
        "第一章直播电商行业发展历程及现状.... - 1 - "
        "第一节直播电商的定义.... - 1 - "
        "一、直播电商的定义与特征.... - 1 - "
        "二、直播电商行业发展历程...... - 2 - "
        "第二节直播电商的形态.... - 5 - "
    )
    entries = _classify_toc_concat_block(text)
    assert entries is not None
    assert len(entries) >= 4


def test_concat_toc_block_rejects_normal_paragraph():
    text = (
        "本白皮书系统梳理了直播电商行业从快速扩张到规范发展的演进路径，"
        "指出其在成为数字经济关键增长动力的同时，亦面临内容治理、责任界定与主体规范等多重挑战。"
    )
    assert _classify_toc_concat_block(text) is None


def test_concat_toc_block_extraction_via_convert():
    """The single MinerU concat-TOC paragraph (sample 4abe6b71… p7) must
    end up in payload.toc, not in body_markdown."""
    huge_toc = (
        "第一章 总则 .......... 1 "
        "第一节 适用范围 ............. 3 "
        "一、定义 ........ 5 "
        "二、术语 .... 7 "
        "第二章 业务 ......... 9 "
    )
    pdf_info = [{
        "page_idx": 7,
        "para_blocks": [
            {"type": "text", "bbox": [10, 10, 500, 200],
             "lines": [{"spans": [{"type": "text", "content": huge_toc}]}]},
            {"type": "text", "bbox": [10, 210, 500, 400],
             "lines": [{"spans": [{"type": "text", "content": "正文从这里开始。"}]}]},
        ],
    }]
    blocks, md, toc = convert(pdf_info, image_uris={}, image_analyzer=None, storage=None)
    assert len(toc) >= 4
    # TOC content removed from body markdown.
    for needle in ("总则", "适用范围", "定义", "术语", "业务"):
        assert needle not in md, f"TOC remnant in body: {needle}"
    # Body content survives.
    assert "正文从这里开始" in md
