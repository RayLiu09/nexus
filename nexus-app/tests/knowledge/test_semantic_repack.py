"""Tests for nexus_app.knowledge.semantic_repack (slice 2).

Each test class covers one operator in isolation, then ``TestRepackPipeline``
exercises the full ``repack()`` entry point end-to-end. The locator-contract
checks (md_char_range / md_spans / heading_path / anchor_role) live in
``test_chunk_builder_locator.py`` — this file focuses on the segmentation
rules themselves.
"""
from __future__ import annotations

from nexus_app.knowledge.semantic_repack import (
    attach_attribution,
    decompose_atomic_tables,
    drop_meaningless,
    drop_navigational,
    enrich_context,
    merge_continuation,
    repack,
)


# ---------------------------------------------------------------------------
# Block factories (mirror mineru_converter shapes)
# ---------------------------------------------------------------------------


def _h(seq: int, text: str, *, page: int = 0, level: int = 1, bid: str | None = None) -> dict:
    return {
        "block_id": bid or f"h-{seq}",
        "block_type": "heading",
        "seq_no": seq,
        "page": page,
        "bbox": [0.0, 0.0, 100.0, 20.0],
        "text": text,
        "heading_level": level,
        "md_char_range": [seq * 100, seq * 100 + len(text)],
    }


def _p(seq: int, text: str, *, page: int = 0, bid: str | None = None, role: str | None = None) -> dict:
    block: dict = {
        "block_id": bid or f"p-{seq}",
        "block_type": "paragraph",
        "seq_no": seq,
        "page": page,
        "bbox": [0.0, float(seq * 50), 100.0, float(seq * 50 + 40)],
        "text": text,
        "md_char_range": [seq * 1000, seq * 1000 + len(text)],
    }
    if role is not None:
        block["metadata"] = {"role": role}
    return block


def _t(seq: int, md: str, *, page: int = 0, caption: str | None = None, bid: str | None = None) -> dict:
    return {
        "block_id": bid or f"t-{seq}",
        "block_type": "table",
        "seq_no": seq,
        "page": page,
        "bbox": [0.0, 0.0, 200.0, 200.0],
        "content": md,
        "caption": caption,
        "md_char_range": [seq * 1000, seq * 1000 + len(md)],
    }


def _img(seq: int, *, page: int = 0, caption: str | None = None, bid: str | None = None) -> dict:
    return {
        "block_id": bid or f"img-{seq}",
        "block_type": "image",
        "seq_no": seq,
        "page": page,
        "bbox": [0.0, 0.0, 100.0, 100.0],
        "image_uris": ["s3://test.png"],
        "caption": caption,
        "md_char_range": [seq * 1000, seq * 1000 + 10],
    }


# ---------------------------------------------------------------------------
# drop_navigational
# ---------------------------------------------------------------------------


class TestDropNavigational:
    def test_drops_heading_blocks(self):
        blocks = [_h(1, "第一章"), _p(2, "正文段落 X")]
        kept = drop_navigational(blocks)
        assert [b["block_id"] for b in kept] == ["p-2"]

    def test_drops_document_metadata_role(self):
        blocks = [
            _p(1, "标题区", role="document_metadata"),
            _p(2, "正文段落 X"),
        ]
        kept = drop_navigational(blocks)
        assert [b["block_id"] for b in kept] == ["p-2"]

    def test_drops_legacy_hash_prefixed_paragraph(self):
        """Back-compat: adapter that emits '# H1' as a paragraph still loses it."""
        blocks = [_p(1, "# 旧式标题"), _p(2, "正文段落 X")]
        kept = drop_navigational(blocks)
        assert [b["block_id"] for b in kept] == ["p-2"]

    def test_preserves_normal_paragraphs(self):
        blocks = [_p(1, "段落 A"), _p(2, "段落 B"), _t(3, "| a | b |\n| 1 | 2 |")]
        kept = drop_navigational(blocks)
        assert len(kept) == 3


# ---------------------------------------------------------------------------
# drop_meaningless
# ---------------------------------------------------------------------------


class TestDropMeaningless:
    def test_drops_pure_page_number(self):
        kept = drop_meaningless([_p(1, "12"), _p(2, "正文段落正常长度")])
        assert [b["block_id"] for b in kept] == ["p-2"]

    def test_drops_page_footer_patterns(self):
        for footer in ["第 12 页", "第 12 页 / 共 80 页", "- 12 -", "Page 12 of 80", "P.12"]:
            kept = drop_meaningless([_p(1, footer), _p(2, "正文段落正常长度")])
            assert [b["block_id"] for b in kept] == ["p-2"], f"footer={footer!r}"

    def test_drops_pure_punctuation(self):
        for s in ["……", "———", "***", "•••", "。。。"]:
            kept = drop_meaningless([_p(1, s), _p(2, "正文段落正常长度")])
            assert [b["block_id"] for b in kept] == ["p-2"], f"text={s!r}"

    def test_drops_ultra_short_orphan(self):
        kept = drop_meaningless([_p(1, "ab"), _p(2, "正文段落正常长度")])
        assert [b["block_id"] for b in kept] == ["p-2"]

    def test_drops_decorative_blocks(self):
        b = _p(1, "广告横幅扫码下载")
        b["decorative"] = True
        kept = drop_meaningless([b, _p(2, "正文段落正常长度")])
        assert [b["block_id"] for b in kept] == ["p-2"]

    def test_preserves_media_regardless_of_text(self):
        """Empty caption table must NOT be dropped — its bbox + image is the chunk."""
        empty_table = _t(1, "")
        kept = drop_meaningless([empty_table])
        assert [b["block_id"] for b in kept] == ["t-1"]

    def test_preserves_short_paragraph_above_threshold(self):
        """A 4-character meaningful paragraph survives — threshold is exclusive."""
        kept = drop_meaningless([_p(1, "三亚游记")])
        assert [b["block_id"] for b in kept] == ["p-1"]


# ---------------------------------------------------------------------------
# attach_attribution
# ---------------------------------------------------------------------------


class TestAttachAttribution:
    def test_folds_source_paragraph_into_preceding_table(self):
        blocks = [
            _t(1, "| a | b |\n| 1 | 2 |", caption="表 3-1 政策一览", page=5),
            _p(2, "数据来源：国家网信办", page=5),
        ]
        out = attach_attribution(blocks)
        assert len(out) == 1
        assert out[0]["block_id"] == "t-1"
        children = out[0]["attribution_children"]
        assert [c["block_id"] for c in children] == ["p-2"]

    def test_folds_figure_caption_into_following_image(self):
        blocks = [
            _p(1, "图 2-3 行业增长趋势", page=8),
            _img(2, page=8, caption=None),
        ]
        out = attach_attribution(blocks)
        # caption-only paragraph should fold into the image that follows
        assert len(out) == 1
        assert out[0]["block_id"] == "img-2"
        assert [c["block_id"] for c in out[0]["attribution_children"]] == ["p-1"]

    def test_keeps_attribution_when_no_neighbouring_media(self):
        blocks = [
            _p(1, "正文段落正常长度", page=5),
            _p(2, "数据来源：国家网信办", page=5),
            _p(3, "另一段正文也是正常长度", page=6),
        ]
        out = attach_attribution(blocks)
        # no media neighbour — the attribution survives standalone
        assert [b["block_id"] for b in out] == ["p-1", "p-2", "p-3"]

    def test_does_not_attach_when_pages_too_far(self):
        blocks = [
            _t(1, "| a |", caption="表 1", page=2),
            _p(2, "数据来源：xxx", page=10),
        ]
        out = attach_attribution(blocks)
        assert "attribution_children" not in out[0]

    def test_ignores_long_attribution_like_text(self):
        """A paragraph beginning with '数据来源:' but 200 chars long is real body text."""
        body = "数据来源：" + "X" * 200
        blocks = [_t(1, "| a |", page=5), _p(2, body, page=5)]
        out = attach_attribution(blocks)
        assert "attribution_children" not in out[0]


# ---------------------------------------------------------------------------
# merge_continuation
# ---------------------------------------------------------------------------


class TestMergeContinuation:
    def test_merges_cross_page_unterminated_paragraph(self):
        blocks = [
            _p(1, "本章讨论的核心问题在于平台治理能力", page=10),  # no terminator
            _p(2, "因此需要建立分级监管框架。", page=11),
        ]
        out = merge_continuation(blocks)
        assert len(out) == 1
        assert out[0]["merged_from"] == ["p-1", "p-2"]
        assert "本章讨论的核心问题在于平台治理能力" in out[0]["text"]
        assert "因此需要建立分级监管框架。" in out[0]["text"]

    def test_does_not_merge_across_heading_boundary_removed_from_candidates(self):
        original = [
            _p(1, "图表说明没有句号", page=37),
            _h(2, "第二章 新章节", page=38, level=2),
            _p(3, "新章节导语。", page=38),
        ]
        candidates = [original[0], original[2]]
        out = merge_continuation(candidates, original_blocks=original)
        assert [b["block_id"] for b in out] == ["p-1", "p-3"]

    def test_does_not_merge_when_first_paragraph_ends_with_period(self):
        blocks = [
            _p(1, "第一句话已经完结。", page=10),
            _p(2, "第二句话是新主题。", page=11),
        ]
        out = merge_continuation(blocks)
        assert [b["block_id"] for b in out] == ["p-1", "p-2"]

    def test_does_not_merge_when_next_starts_with_list_marker(self):
        blocks = [
            _p(1, "下面是几个要点", page=10),  # no terminator
            _p(2, "1. 要点一", page=11),
        ]
        out = merge_continuation(blocks)
        assert [b["block_id"] for b in out] == ["p-1", "p-2"]

    def test_does_not_merge_across_many_pages(self):
        blocks = [
            _p(1, "未完成的句子", page=5),
            _p(2, "另一段的开头", page=20),
        ]
        out = merge_continuation(blocks)
        assert len(out) == 2

    def test_chains_three_paragraphs(self):
        blocks = [
            _p(1, "段落 A 未结束", page=10),
            _p(2, "段落 B 也未结束", page=11),
            _p(3, "段落 C 终于结束了。", page=12),
        ]
        out = merge_continuation(blocks)
        assert len(out) == 1
        assert out[0]["merged_from"] == ["p-1", "p-2", "p-3"]


# ---------------------------------------------------------------------------
# decompose_atomic_tables
# ---------------------------------------------------------------------------


class TestDecomposeAtomicTables:
    def test_splits_record_table_into_overview_and_rows(self):
        md = """| 发布时间 | 部门 | 文件名 | 内容摘要 |
| --- | --- | --- | --- |
| 2021.04 | 国家网信办等七部门 | 《网络直播营销管理办法》 | 平台应建立审核机制 |
| 2022.03 | 市场监管总局 | 《网络交易监管办法》 | 强化平台责任 |"""
        block = _t(1, md, caption="表 3-1 政策一览", bid="tbl-1")
        block["md_char_range"] = [0, len(md)]
        out = decompose_atomic_tables([block], body_markdown=md)

        assert [b["block_type"] for b in out] == ["table", "table_row", "table_row"]
        assert out[0]["content"] == "表格概览：共 2 条记录；字段：发布时间 / 部门 / 文件名 / 内容摘要"
        assert out[1]["block_id"] == "tbl-1#row-1"
        assert out[1]["content"] == (
            "表 3-1 政策一览 | 发布时间: 2021.04 | 部门: 国家网信办等七部门 | "
            "文件名: 《网络直播营销管理办法》 | 内容摘要: 平台应建立审核机制"
        )
        assert out[1]["_unit_metadata"]["table_row_index"] == 1
        assert out[1]["_unit_metadata"]["locator_precision"] == "markdown_row"
        assert out[1]["_source_blocks"][0]["md_char_range"] == [
            md.index("| 2021.04"),
            md.index("| 2021.04") + len("| 2021.04 | 国家网信办等七部门 | 《网络直播营销管理办法》 | 平台应建立审核机制 |"),
        ]

    def test_merges_table_continuation_rows_into_previous_record(self):
        md = """| 发布时间 | 部门 | 名称 | 内容摘要 |
| --- | --- | --- | --- |
| 2020.11 | 广电总局 | 《关于加强网络直播管理的通知》 | 对开设直播带货的商家进行资质审查 |
|  |  |  | 准预警和及时阻断。 |
| 2021.02 | 国家网信办等七部门 | 《关于加强网络直播规范管理工作的指导意见》 | 建立健全制度规范。 |"""
        block = _t(1, md, caption="表 3-1 政策一览", bid="tbl-1")
        block["md_char_range"] = [0, len(md)]
        out = decompose_atomic_tables([block], body_markdown=md)

        assert [b["block_type"] for b in out] == ["table", "table_row", "table_row"]
        assert out[0]["_unit_metadata"]["table_row_count"] == 2
        assert "资质审查 准预警和及时阻断。" in out[1]["content"]
        assert out[1]["_unit_metadata"]["table_row_cells"][3].endswith("准预警和及时阻断。")
        assert out[2]["content"].startswith("表 3-1 政策一览 | 发布时间: 2021.02")

    def test_does_not_split_two_column_key_value_table(self):
        md = """| 字段 | 值 |
| --- | --- |
| 标题 | 白皮书 |
| 日期 | 2026 年 |"""
        out = decompose_atomic_tables([_t(1, md, caption="元数据表")], body_markdown=md)
        assert len(out) == 1
        assert out[0]["block_type"] == "table"

    def test_does_not_split_matrix_table(self):
        md = """| 指标 | 2022 | 2023 | 2024 | 2025 |
| --- | --- | --- | --- | --- |
| 市场规模 | 26704 | 37761 | 45146 | 52587 |
| 增速 | 41.41% | 19.56% | 16.48% | 16.48% |"""
        out = decompose_atomic_tables([_t(1, md, caption="图表数据")], body_markdown=md)
        assert len(out) == 1
        assert out[0]["block_type"] == "table"

    def test_metadata_hint_can_force_split_or_no_split(self):
        md = """| A | B | C |
| --- | --- | --- |
| 1 | 2 | 3 |
| 4 | 5 | 6 |"""
        forced = _t(1, md)
        forced["metadata"] = {"semantic_table_type": "row_atomic"}
        assert [b["block_type"] for b in decompose_atomic_tables([forced], body_markdown=md)] == [
            "table", "table_row", "table_row"
        ]

        blocked = _t(2, md)
        blocked["metadata"] = {"semantic_table_type": "matrix"}
        assert len(decompose_atomic_tables([blocked], body_markdown=md)) == 1


# ---------------------------------------------------------------------------
# enrich_context (heading_path, anchor_role, captions)
# ---------------------------------------------------------------------------


class TestEnrichContext:
    def test_attaches_h1_h2_h3_path(self):
        originals = [
            _h(1, "# 第一章 总论", level=1),
            _h(2, "## 第一节 背景", level=2),
            _h(3, "### 一、政策环境", level=3),
            _p(4, "正文段落正常长度"),
        ]
        units = enrich_context([_p(4, "正文段落正常长度")], original_blocks=originals)
        assert len(units) == 1
        titles = [h["title"] for h in units[0]["heading_path"]]
        assert titles == ["第一章 总论", "第一节 背景", "一、政策环境"]

    def test_collapses_deeper_levels_into_h3_slot(self):
        originals = [
            _h(1, "# 章", level=1),
            _h(2, "## 节", level=2),
            _h(3, "### 三", level=3),
            _h(4, "#### 子项", level=4),
            _p(5, "正文段落正常长度"),
        ]
        units = enrich_context([_p(5, "正文段落正常长度")], original_blocks=originals)
        # h4 squashed into h3 slot — last entry should be the h4 title
        assert units[0]["heading_path"][-1]["title"] == "子项"
        assert units[0]["heading_path"][-1]["level"] == 3

    def test_resets_deeper_when_higher_level_appears(self):
        originals = [
            _h(1, "# 章 A", level=1),
            _h(2, "## 节 A1", level=2),
            _h(5, "# 章 B", level=1),  # new chapter — clears § A1
            _p(6, "B 章正文正常长度"),
        ]
        units = enrich_context([_p(6, "B 章正文正常长度")], original_blocks=originals)
        titles = [h["title"] for h in units[0]["heading_path"]]
        assert titles == ["章 B"]

    def test_anchor_role_per_block_type(self):
        originals = [
            _p(1, "x"), _t(2, "x"), _img(3, caption="图 1"), _h(4, "# h"),
        ]
        units = enrich_context(
            [
                _p(1, "正文段落正常长度"),
                _t(2, "| x |"),
                _img(3, caption="图 1"),
            ],
            original_blocks=originals,
        )
        roles = [u["anchor_role"] for u in units]
        assert roles == ["body", "table_overview", "image"]

    def test_caption_only_on_media(self):
        originals = [_t(1, "x", caption="表 1")]
        units = enrich_context(
            [_t(1, "| x |", caption="表 1")], original_blocks=originals
        )
        assert units[0]["caption"] == "表 1"

    def test_md_spans_emitted_only_for_merged_units(self):
        merged_block = {
            "block_id": "merged",
            "block_type": "paragraph",
            "seq_no": 1,
            "page": 5,
            "text": "AB",
            "merged_from": ["p-1", "p-2"],
            "_merged_blocks": [
                {
                    "block_id": "p-1", "page": 5, "bbox": [0, 0, 1, 1],
                    "md_char_range": [10, 20],
                },
                {
                    "block_id": "p-2", "page": 6, "bbox": [0, 0, 1, 1],
                    "md_char_range": [25, 35],
                },
            ],
        }
        units = enrich_context([merged_block], original_blocks=[])
        assert units[0]["md_spans"] == [
            {"start": 10, "end": 20, "block_id": "p-1"},
            {"start": 25, "end": 35, "block_id": "p-2"},
        ]

    def test_md_spans_includes_attribution_children(self):
        host = _t(1, "| x |", caption="表 1", page=5)
        attr = _p(2, "数据来源：X", page=5)
        host["attribution_children"] = [attr]
        units = enrich_context([host], original_blocks=[])
        assert units[0]["md_spans"] is not None
        ids = [s["block_id"] for s in units[0]["md_spans"]]
        assert ids == ["t-1", "p-2"]


# ---------------------------------------------------------------------------
# Full pipeline integration
# ---------------------------------------------------------------------------


class TestRepackPipeline:
    def test_end_to_end_segments_a_realistic_section(self):
        blocks = [
            _h(1, "# 第三章 行业治理", level=1),
            _h(2, "## 第一节 政策框架", level=2),
            _p(3, "本节梳理 2020 年以来的政策演进。"),
            _p(4, "12"),  # page number — drop
            _p(5, "其中代表性政策包括但不限于以下几项。"),
            _t(6, "| 时间 | 政策 |\n| 2021 | 直播办法 |", caption="表 3-1 政策一览"),
            _p(7, "数据来源：国家网信办"),  # attribution → fold into t-6
            _p(8, "上述政策标志着治理进入新阶段。"),
        ]
        units = repack(blocks)
        # heading-only block 1/2 and pagenum 4 should be gone;
        # t-6 absorbs p-7; p-3, p-5, p-8 become individual units
        assert len(units) == 4
        roles = [u["anchor_role"] for u in units]
        assert "table_overview" in roles
        # heading_path must propagate to all units
        for u in units:
            assert any(h["title"] == "第三章 行业治理" for h in u["heading_path"])
            assert any(h["title"] == "第一节 政策框架" for h in u["heading_path"])
        # table unit must contain the folded attribution text
        table_unit = next(u for u in units if u["anchor_role"] == "table_overview")
        assert "数据来源" in table_unit["content"]
        assert table_unit["caption"] == "表 3-1 政策一览"

    def test_repack_emits_table_row_units_only_for_atomic_record_table(self):
        md = """| 发布时间 | 部门 | 文件名 | 内容摘要 |
| --- | --- | --- | --- |
| 2021.04 | 国家网信办等七部门 | 《网络直播营销管理办法》 | 平台应建立审核机制 |
| 2022.03 | 市场监管总局 | 《网络交易监管办法》 | 强化平台责任 |"""
        blocks = [_h(1, "# 政策", level=1), _t(2, md, caption="表 3-1 政策一览", bid="tbl-1")]
        blocks[1]["md_char_range"] = [0, len(md)]

        units = repack(blocks, body_markdown=md)
        roles = [u["anchor_role"] for u in units]
        assert roles == ["table_overview", "table_row", "table_row"]
        assert units[1]["metadata"]["table_parent_block_id"] == "tbl-1"
        assert units[1]["metadata"]["table_columns"] == ["发布时间", "部门", "文件名", "内容摘要"]
        assert units[1]["source_blocks"][0]["block_id"] == "tbl-1"
        assert units[1]["source_blocks"][0]["md_char_range"][0] == md.index("| 2021.04")
        assert units[1]["heading_path"][0]["title"] == "政策"

    def test_drops_empty_media_without_caption_or_text(self):
        units = repack([_img(1, caption="")])
        assert units == []

    def test_empty_blocks_returns_empty_list(self):
        assert repack([]) == []

    def test_drops_document_metadata_blocks(self):
        blocks = [
            _h(1, "# T", level=1),
            _p(2, "市场监管总局发展研究中心", role="document_metadata"),
            _p(3, "2026 年 1 月", role="document_metadata"),
            _p(4, "正文段落正常长度"),
        ]
        units = repack(blocks)
        # only p-4 survives
        assert len(units) == 1
        sids = [b["block_id"] for b in units[0]["source_blocks"]]
        assert sids == ["p-4"]
