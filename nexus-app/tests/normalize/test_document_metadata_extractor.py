"""Tests for nexus_app.normalize.document_metadata_extractor (slice 0+1).

Per docs/rag_semantic_chunks_implementation_plan.md §五, document-level
metadata (title, authors, publish_date, keywords, abstract, outline) is
extracted by rule from the leading blocks of a normalized document and
written to ``normalized_ref.document_metadata`` — NOT duplicated into
per-chunk metadata downstream.
"""
from __future__ import annotations

from nexus_app.normalize.document_metadata_extractor import extract


def _h(idx: int, text: str, page: int = 0) -> dict:
    return {
        "block_id": f"block-h-{idx}",
        "block_type": "heading",
        "page": page,
        "text": text,
        "md_char_range": [0, len(text)],
    }


def _p(idx: int, text: str, page: int = 0) -> dict:
    return {
        "block_id": f"block-p-{idx}",
        "block_type": "paragraph",
        "page": page,
        "text": text,
        "md_char_range": [0, len(text)],
    }


class TestTitle:
    def test_extracts_title_from_first_h1_heading(self):
        blocks = [
            _h(1, "# 2025 直播电商行业发展白皮书", page=0),
            _p(2, "市场监管总局发展研究中心", page=0),
        ]
        md, ids = extract(blocks, body_markdown="", toc=None)
        assert md["title"] == "2025 直播电商行业发展白皮书"
        assert "block-h-1" in ids

    def test_title_strips_leading_hashes_and_whitespace(self):
        blocks = [_h(1, "###   测试标题   ", page=0)]
        md, _ = extract(blocks, body_markdown="", toc=None)
        assert md["title"] == "测试标题"

    def test_no_title_when_no_heading(self):
        blocks = [_p(1, "纯正文 no heading", page=0)]
        md, _ = extract(blocks, body_markdown="", toc=None)
        assert md["title"] is None


class TestAuthorsAndPublishDate:
    def test_extracts_authors_and_date_after_title(self):
        blocks = [
            _h(1, "# 2025 直播电商行业发展白皮书"),
            _p(2, "市场监管总局发展研究中心"),
            _p(3, "中国社会科学院财经战略研究院课题组"),
            _p(4, "2026 年 1 月"),
            _h(5, "## 导论"),
        ]
        md, ids = extract(blocks, body_markdown="", toc=None)
        assert md["authors"] == [
            "市场监管总局发展研究中心",
            "中国社会科学院财经战略研究院课题组",
        ]
        assert md["publish_date"] == "2026-01"
        assert {"block-p-2", "block-p-3", "block-p-4"} <= ids

    def test_recognises_multiple_date_formats(self):
        for raw, expected in [
            ("2026 年 1 月", "2026-01"),
            ("2026 年 1 月 15 日", "2026-01-15"),
            ("2026-03", "2026-03"),
            ("2026-03-15", "2026-03-15"),
            ("2025.12", "2025-12"),
        ]:
            blocks = [
                _h(1, "# T"),
                _p(2, raw),
                _h(3, "## 导论"),
            ]
            md, _ = extract(blocks, body_markdown="", toc=None)
            assert md["publish_date"] == expected, f"raw={raw!r}"

    def test_stops_collecting_authors_at_long_paragraph(self):
        """Once a real body paragraph starts (≥80 chars) the cover-page
        scan should halt — the long para is body, not metadata."""
        blocks = [
            _h(1, "# T"),
            _p(2, "市场监管总局发展研究中心"),
            _p(3, "x" * 200),  # ← body content kicks in
            _p(4, "中国社会科学院财经战略研究院课题组"),  # should NOT be picked
        ]
        md, ids = extract(blocks, body_markdown="", toc=None)
        assert md["authors"] == ["市场监管总局发展研究中心"]
        assert "block-p-4" not in ids


class TestKeywords:
    def test_extracts_keywords_split_by_chinese_punctuation(self):
        blocks = [
            _h(1, "# T"),
            _p(2, "关键词：直播电商；规范化；政策；监管；协同治理。"),
        ]
        md, ids = extract(blocks, body_markdown="", toc=None)
        assert md["keywords"] == ["直播电商", "规范化", "政策", "监管", "协同治理"]
        assert "block-p-2" in ids

    def test_keywords_with_english_separators(self):
        blocks = [
            _h(1, "# T"),
            _p(2, "关键词: A; B, C、D E"),
        ]
        md, _ = extract(blocks, body_markdown="", toc=None)
        assert md["keywords"] == ["A", "B", "C", "D", "E"]

    def test_no_keywords_when_no_marker(self):
        blocks = [_h(1, "# T"), _p(2, "随便一段普通话")]
        md, _ = extract(blocks, body_markdown="", toc=None)
        assert md["keywords"] == []


class TestAbstract:
    def test_aggregates_abstract_from_paragraphs_after_导论(self):
        blocks = [
            _h(1, "# T"),
            _h(2, "## 导论"),
            _p(3, "直播电商是近年来增长最快的商业模式..."),
            _p(4, "本白皮书系统梳理了行业演进路径..."),
            _p(5, "关键词：直播电商；规范化；"),  # halt before keywords
            _h(6, "## 第一章"),
        ]
        md, ids = extract(blocks, body_markdown="", toc=None)
        assert md["abstract"] is not None
        assert "直播电商是近年来" in md["abstract"]
        assert "本白皮书系统梳理" in md["abstract"]
        assert "关键词" not in md["abstract"]
        assert {"block-h-2", "block-p-3", "block-p-4"} <= ids
        # block-p-5 IS contributed (the keywords-scan step claims it), but it
        # must NOT be part of the abstract text.
        assert "block-p-5" in ids
        assert md["keywords"] == ["直播电商", "规范化"]

    def test_abstract_supports_alternate_section_names(self):
        for header in ("摘要", "前言", "概述", "引言", "Abstract"):
            blocks = [
                _h(1, "# T"),
                _h(2, f"## {header}"),
                _p(3, "正文段落 X"),
                _h(4, "## 第一章"),
            ]
            md, _ = extract(blocks, body_markdown="", toc=None)
            assert md["abstract"] == "正文段落 X", f"header={header}"

    def test_no_abstract_when_no_known_section(self):
        blocks = [_h(1, "# T"), _p(2, "随便一段")]
        md, _ = extract(blocks, body_markdown="", toc=None)
        assert md["abstract"] is None


class TestOutline:
    def test_outline_passes_through_from_toc(self):
        toc = [
            {"level": 1, "title": "第一章", "page": 1},
            {"level": 2, "title": "第一节", "page": 1},
        ]
        md, _ = extract([_h(1, "# T")], body_markdown="", toc=toc)
        assert md["outline"] == toc

    def test_outline_empty_when_no_toc(self):
        md, _ = extract([_h(1, "# T")], body_markdown="", toc=None)
        assert md["outline"] == []


class TestEmptyAndFallbacks:
    def test_empty_blocks_returns_empty_metadata(self):
        md, ids = extract([], body_markdown="", toc=None)
        assert md["title"] is None
        assert md["authors"] == []
        assert md["keywords"] == []
        assert md["outline"] == []
        assert ids == set()

    def test_resolves_text_via_md_char_range_when_text_absent(self):
        body_md = "# 全文档标题\n\n市场监管总局"
        blocks = [
            {
                "block_id": "block-h-1",
                "block_type": "heading",
                "page": 0,
                "md_char_range": [0, 8],  # "# 全文档标题"
            },
            {
                "block_id": "block-p-2",
                "block_type": "paragraph",
                "page": 0,
                "md_char_range": [10, 16],  # "市场监管总局"
            },
        ]
        md, _ = extract(blocks, body_markdown=body_md, toc=None)
        assert md["title"] == "全文档标题"

    def test_source_block_ids_are_sorted(self):
        blocks = [
            _h(1, "# T"),
            _p(2, "市场监管总局发展研究中心"),
            _p(3, "2026 年 1 月"),
        ]
        md, _ = extract(blocks, body_markdown="", toc=None)
        # sorted, not insertion order
        assert md["source_block_ids"] == sorted(md["source_block_ids"])
