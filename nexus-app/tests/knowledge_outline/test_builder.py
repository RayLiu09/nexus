"""Unit tests for the deterministic outline builder.

Covers tree shape, depth truncation, non-monotonic heading levels, leaf-only
anchor / chunk enforcement, numbering parsing, and the empty-input fallback.
"""

from __future__ import annotations

import pytest

from nexus_app.knowledge_outline.builder import (
    HeadingInput,
    build_outline,
    parse_numbering,
)


def _h(
    title: str,
    level: int,
    *,
    anchor: dict | None = None,
    chunks: list[str] | None = None,
    blocks: list[str] | None = None,
) -> HeadingInput:
    return HeadingInput(
        title=title,
        level=level,
        anchor_range=anchor,
        chunk_ids=list(chunks or []),
        source_block_ids=list(blocks or []),
    )


# ---------------------------------------------------------------------------
# Well-formed trees
# ---------------------------------------------------------------------------


def test_builds_well_formed_three_level_tree():
    headings = [
        _h("第1章 引论", 1),
        _h("1.1 概念", 2),
        _h("1.1.1 定义", 3, chunks=["c1"], anchor={"start": 0}),
        _h("1.1.2 边界", 3, chunks=["c2"], anchor={"start": 10}),
        _h("1.2 原理", 2, chunks=["c3"], anchor={"start": 20}),
        _h("第2章 应用", 1),
        _h("2.1 案例", 2, chunks=["c4"], anchor={"start": 30}),
    ]

    result = build_outline(headings, root_title="教材A")

    assert result.fallback_used is False
    assert result.max_depth == 3
    assert result.root.level == 0
    assert result.root.title == "教材A"
    assert result.total_nodes == 1 + len(headings)

    def _by_title(title: str):
        return next(n for n in result.nodes if n.title == title)

    chap1 = _by_title("第1章 引论")
    chap2 = _by_title("第2章 应用")
    s11 = _by_title("1.1 概念")
    s12 = _by_title("1.2 原理")
    d111 = _by_title("1.1.1 定义")
    d112 = _by_title("1.1.2 边界")

    assert chap1.parent_id == result.root.id
    assert chap1.level == 1
    assert chap1.order_index == 0
    assert chap2.order_index == 1

    assert s11.parent_id == chap1.id and s11.level == 2
    assert s12.parent_id == chap1.id and s12.order_index == 1

    assert d111.parent_id == s11.id and d111.level == 3
    assert d112.parent_id == s11.id and d112.order_index == 1


def test_leaves_carry_anchor_and_chunks_but_non_leaves_do_not():
    headings = [
        _h("A", 1, anchor={"start": 0}, chunks=["ca"]),
        _h("A.1", 2, anchor={"start": 5}, chunks=["ca1"]),
        _h("B", 1, anchor={"start": 20}, chunks=["cb"]),
    ]

    result = build_outline(headings, root_title="doc")

    a = next(n for n in result.nodes if n.title == "A")
    a1 = next(n for n in result.nodes if n.title == "A.1")
    b = next(n for n in result.nodes if n.title == "B")

    # A has a child (A.1) — must be non-leaf: no anchor / chunks.
    assert a.anchor_range is None
    assert a.chunk_ids == []

    # A.1 and B have no children — leaves.
    assert a1.anchor_range == {"start": 5}
    assert a1.chunk_ids == ["ca1"]
    assert b.anchor_range == {"start": 20}
    assert b.chunk_ids == ["cb"]


# ---------------------------------------------------------------------------
# Depth truncation and edge cases
# ---------------------------------------------------------------------------


def test_deeper_than_three_headings_flatten_to_l3_siblings():
    headings = [
        _h("Ch", 1),
        _h("Sec", 2),
        _h("Sub", 3, chunks=["c-sub"]),
        _h("H4", 4, chunks=["c-h4"]),
        _h("H5", 5, chunks=["c-h5"]),
        _h("Sub2", 3, chunks=["c-sub2"]),
    ]

    result = build_outline(headings, root_title="doc")

    assert result.max_depth == 3
    for node in result.nodes:
        assert node.level <= 3

    sec = next(n for n in result.nodes if n.title == "Sec")
    sub = next(n for n in result.nodes if n.title == "Sub")
    h4 = next(n for n in result.nodes if n.title == "H4")
    h5 = next(n for n in result.nodes if n.title == "H5")
    sub2 = next(n for n in result.nodes if n.title == "Sub2")

    # All L3+ headings become siblings under Sec. Sub remains a leaf and keeps
    # its own chunks; deeper headings appear as adjacent leaves rather than
    # being nested under Sub (which would violate the 3-level constraint).
    for node in (sub, h4, h5, sub2):
        assert node.parent_id == sec.id
        assert node.level == 3

    assert sub.chunk_ids == ["c-sub"]
    assert h4.chunk_ids == ["c-h4"]
    assert h5.chunk_ids == ["c-h5"]
    assert sub2.chunk_ids == ["c-sub2"]


def test_non_monotonic_levels_still_form_valid_tree():
    # h1 → h3 (skips h2). h3 should be treated as a child of h1, not lost.
    headings = [
        _h("Ch", 1),
        _h("Sub", 3, chunks=["c1"]),
        _h("Ch2", 1),
    ]

    result = build_outline(headings, root_title="doc")

    ch = next(n for n in result.nodes if n.title == "Ch")
    sub = next(n for n in result.nodes if n.title == "Sub")
    ch2 = next(n for n in result.nodes if n.title == "Ch2")

    assert sub.parent_id == ch.id
    assert ch2.parent_id == result.root.id
    assert sub.level == 3  # display level from input


def test_shallowest_level_greater_than_one_gets_normalized_to_one():
    headings = [
        _h("Ch", 2),
        _h("Sec", 3, chunks=["c1"]),
    ]

    result = build_outline(headings, root_title="doc")

    ch = next(n for n in result.nodes if n.title == "Ch")
    sec = next(n for n in result.nodes if n.title == "Sec")

    assert ch.level == 1
    assert sec.level == 2
    assert sec.parent_id == ch.id


def test_empty_headings_yields_fallback_root():
    result = build_outline([], root_title="书名")

    assert result.fallback_used is True
    assert result.total_nodes == 1
    assert result.max_depth == 0
    assert result.root.parent_id is None
    assert result.root.title == "书名"
    assert result.root.level == 0


def test_empty_headings_with_no_root_title_uses_fallback_label():
    result = build_outline([], root_title="")

    assert result.root.title == "全文"


# ---------------------------------------------------------------------------
# Ordering and identity
# ---------------------------------------------------------------------------


def test_order_index_is_stable_within_siblings():
    headings = [
        _h("Alpha", 1),
        _h("Beta", 1),
        _h("Gamma", 1),
        _h("A.1", 2),
        _h("A.2", 2),
    ]
    # Note: A.1 / A.2 land under Gamma (latest L1 on stack). Testing order.

    result = build_outline(headings, root_title="doc")

    alpha = next(n for n in result.nodes if n.title == "Alpha")
    beta = next(n for n in result.nodes if n.title == "Beta")
    gamma = next(n for n in result.nodes if n.title == "Gamma")
    a1 = next(n for n in result.nodes if n.title == "A.1")
    a2 = next(n for n in result.nodes if n.title == "A.2")

    assert (alpha.order_index, beta.order_index, gamma.order_index) == (0, 1, 2)
    assert a1.parent_id == gamma.id and a1.order_index == 0
    assert a2.order_index == 1


def test_every_non_root_node_has_a_valid_parent():
    headings = [
        _h(f"H{i}", (i % 3) + 1)
        for i in range(20)
    ]
    result = build_outline(headings, root_title="doc")

    ids = {n.id for n in result.nodes}
    for node in result.nodes:
        if node.parent_id is None:
            assert node.level == 0
        else:
            assert node.parent_id in ids


def test_build_run_id_defaults_and_override():
    result_default = build_outline(
        [_h("X", 1)], root_title="doc",
    )
    assert result_default.build_run_id  # non-empty uuid

    result_custom = build_outline(
        [_h("X", 1)], root_title="doc", build_run_id="run-123",
    )
    assert result_custom.build_run_id == "run-123"


# ---------------------------------------------------------------------------
# Numbering parser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,expected_numbering,expected_path",
    [
        ("1.2.3 深层节标题", "1.2.3", [1, 2, 3]),
        ("1 概述", "1", [1]),
        ("第一章 引论", "第一章", [1]),
        ("第十一章 索引", "第十一章", [11]),
        ("第二十一节 案例", "第二十一节", [21]),
        ("项目3 数据采集", "3", [3]),
        ("模块二 系统概述", "二", [2]),
        ("Chapter 5: Trees", "Chapter 5", [5]),
        ("Introduction", None, None),
        ("", None, None),
    ],
)
def test_parse_numbering_variants(title, expected_numbering, expected_path):
    numbering, path = parse_numbering(title)
    assert numbering == expected_numbering
    assert path == expected_path
