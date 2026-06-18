"""Defect #2 — TOC extraction regression tests.

Locks in:
  - A run of ≥3 consecutive TOC-shaped lines (dot leader / numbered section
    / Chinese chapter) is extracted into payload.toc and stripped from
    body_markdown.
  - An isolated single line that happens to end in a number is NOT mistaken
    for a TOC entry (false-positive guard for body text).
  - When no TOC exists, blocks/markdown stay byte-identical to the
    pre-extraction state.

See docs/document_normalize_defects.md §缺陷 2 for the source defect.
"""
from __future__ import annotations

from nexus_app.pipeline.mineru_converter import convert


def _text_block(content: str, bbox=(10, 10, 100, 30)):
    return {
        "type": "text",
        "bbox": list(bbox),
        "lines": [{"spans": [{"type": "text", "content": content}]}],
    }


def test_dot_leader_toc_run_is_extracted():
    pdf_info = [
        {
            "page_idx": 0,
            "para_blocks": [
                _text_block("第一章 总则 .......... 1"),
                _text_block("1.1 适用范围 ............. 3"),
                _text_block("1.2 术语定义 ........ 5"),
                _text_block("1.3 政策依据 .... 7"),
                _text_block("第二章 行业现状 ......... 9"),
            ],
        },
        {
            "page_idx": 1,
            "para_blocks": [
                _text_block("正文从这里开始。本章梳理行业现状。"),
            ],
        },
    ]
    blocks, md, toc = convert(pdf_info, image_uris={}, image_analyzer=None, storage=None)

    assert len(toc) == 5, f"expected 5 TOC entries, got {len(toc)}: {toc}"
    titles = [e["title"] for e in toc]
    assert "总则" in titles
    assert "适用范围" in titles
    # Page numbers parsed.
    pages = [e["page"] for e in toc]
    assert pages == [1, 3, 5, 7, 9]

    # All TOC lines removed from body_markdown.
    for s in ("总则", "适用范围", "术语定义", "政策依据", "行业现状 ......"):
        assert s not in md, f"TOC artifact still in markdown: {s!r}"

    # Body content survives.
    assert "正文从这里开始" in md
    assert len(blocks) == 1
    # md_char_range still aligns for the survivor.
    r = blocks[0]["md_char_range"]
    assert md[r[0]:r[1]] == "正文从这里开始。本章梳理行业现状。"


def test_numbered_section_toc_extracted_with_level_from_dots():
    pdf_info = [
        {
            "page_idx": 0,
            "para_blocks": [
                _text_block("1 概述 1"),
                _text_block("1.1 背景 3"),
                _text_block("1.1.2 子背景 4"),
                _text_block("正文段落。"),
            ],
        },
    ]
    _, md, toc = convert(pdf_info, image_uris={}, image_analyzer=None, storage=None)
    assert len(toc) == 3
    levels = [e["level"] for e in toc]
    assert levels == [1, 2, 3]
    assert "概述" not in md
    assert "背景" not in md
    assert "正文段落" in md


def test_isolated_line_with_trailing_number_is_not_toc():
    """A single body sentence ending in a digit must NOT be misread as TOC."""
    pdf_info = [
        {
            "page_idx": 0,
            "para_blocks": [
                _text_block("正文：2024 年 GMV 占比上升 12"),
                _text_block("接下来的段落是后续分析。"),
                _text_block("另一段：研究显示头部份额下降到 10"),
            ],
        },
    ]
    _, md, toc = convert(pdf_info, image_uris={}, image_analyzer=None, storage=None)
    assert toc == [], f"isolated digit-ending lines must not be extracted, got {toc}"
    assert "正文：2024 年" in md
    assert "另一段：研究显示" in md


def test_no_toc_means_payload_unchanged():
    pdf_info = [
        {
            "page_idx": 0,
            "para_blocks": [
                _text_block("# 标题"),
                _text_block("第一段正文。"),
                _text_block("第二段正文。"),
            ],
        },
    ]
    blocks, md, toc = convert(pdf_info, image_uris={}, image_analyzer=None, storage=None)
    assert toc == []
    assert len(blocks) == 3
    assert "第一段正文" in md and "第二段正文" in md
