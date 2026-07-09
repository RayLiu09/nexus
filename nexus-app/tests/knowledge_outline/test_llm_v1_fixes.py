"""Unit tests for the three v1 fixes in llm_classifier:

1. Root title fallback ordering: caller > payload.title > ref.title > LLM
   book_title > "全文".
2. Adjacent chapter merge: a short-prefix chapter ("项目一") folds into
   the next chapter ("短视频认知") when they sit within 3 blocks.
3. Chunk backfill coverage: leading front-matter blocks and chapter-intro
   blocks propagate to the first knowledge_point child so no chunk is
   orphaned.
"""

from __future__ import annotations

from nexus_app.knowledge_outline.llm_classifier import (
    HeadingCandidate,
    HeadingClassification,
    build_outline_from_classifications,
)


def _cand(idx: int, block_index: int, text: str) -> HeadingCandidate:
    return HeadingCandidate(
        idx=idx,
        block_id=f"b{block_index}",
        block_index=block_index,
        text=text,
        heading_level=1,
    )


def _cls(idx: int, label: str, conf: float = 0.95) -> HeadingClassification:
    return HeadingClassification(idx=idx, label=label, confidence=conf)


def _blocks(n: int) -> list[dict]:
    return [
        {"block_id": f"b{i}", "block_type": "heading", "text": f"blk-{i}", "page": i // 5 + 1}
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Fix #1 — root title fallback
# ---------------------------------------------------------------------------


def test_caller_root_title_wins_over_llm_book_title():
    cands = [
        _cand(0, 0, "职业教育教材系列"),      # LLM will call this book_title
        _cand(1, 1, "短视频拍摄"),
        _cand(2, 5, "第一章 引论"),
        _cand(3, 8, "一、定义"),
    ]
    cls = [
        _cls(0, "book_title"),
        _cls(1, "book_title"),
        _cls(2, "chapter"),
        _cls(3, "knowledge_point"),
    ]
    result = build_outline_from_classifications(
        cands, cls, _blocks(12),
        root_title="真实书名（来自 payload）",
        build_run_id="run-a",
    )
    assert result.root.title == "真实书名（来自 payload）"


def test_llm_book_title_used_when_caller_is_fallback():
    cands = [
        _cand(0, 0, "系列名"),
        _cand(1, 1, "实际书名"),
        _cand(2, 5, "第一章 引论"),
        _cand(3, 8, "一、定义"),
    ]
    cls = [
        _cls(0, "front_matter"),
        _cls(1, "book_title"),
        _cls(2, "chapter"),
        _cls(3, "knowledge_point"),
    ]
    result = build_outline_from_classifications(
        cands, cls, _blocks(12),
        root_title="全文",  # sentinel: no authoritative caller title
        build_run_id="run-b",
    )
    assert result.root.title == "实际书名"


# ---------------------------------------------------------------------------
# Fix #2 — adjacent chapter merge
# ---------------------------------------------------------------------------


def test_project_prefix_merges_with_next_chapter():
    cands = [
        _cand(0, 0, "项目一"),        # short-prefix stub
        _cand(1, 1, "短视频认知"),    # actual chapter title (1 block later)
        _cand(2, 5, "一、视频定义"),
    ]
    cls = [
        _cls(0, "chapter"),
        _cls(1, "chapter"),
        _cls(2, "knowledge_point"),
    ]
    result = build_outline_from_classifications(
        cands, cls, _blocks(10),
        root_title="教材A", build_run_id="run-c",
    )
    chapters = [n for n in result.nodes if n.level == 1]
    assert len(chapters) == 1
    assert chapters[0].title == "项目一 短视频认知"


def test_di_x_zhang_prefix_merges():
    cands = [
        _cand(0, 0, "第一章"),
        _cand(1, 2, "短视频概述"),
        _cand(2, 6, "一、定义"),
    ]
    cls = [_cls(0, "chapter"), _cls(1, "chapter"), _cls(2, "knowledge_point")]
    result = build_outline_from_classifications(
        cands, cls, _blocks(10), root_title="教材B", build_run_id="run-d",
    )
    chapters = [n for n in result.nodes if n.level == 1]
    assert chapters[0].title == "第一章 短视频概述"


def test_distant_chapters_do_not_merge():
    cands = [
        _cand(0, 0, "项目一"),
        _cand(1, 10, "短视频认知"),   # too far away
        _cand(2, 15, "一、定义"),
    ]
    cls = [_cls(0, "chapter"), _cls(1, "chapter"), _cls(2, "knowledge_point")]
    result = build_outline_from_classifications(
        cands, cls, _blocks(20), root_title="教材C", build_run_id="run-e",
    )
    chapters = [n for n in result.nodes if n.level == 1]
    assert len(chapters) == 2
    assert chapters[0].title == "项目一"
    assert chapters[1].title == "短视频认知"


def test_full_title_chapter_does_not_merge():
    cands = [
        _cand(0, 0, "第一章 短视频概述"),  # already full title
        _cand(1, 1, "第二章 平台介绍"),
        _cand(2, 5, "一、定义"),
    ]
    cls = [_cls(0, "chapter"), _cls(1, "chapter"), _cls(2, "knowledge_point")]
    result = build_outline_from_classifications(
        cands, cls, _blocks(10), root_title="教材D", build_run_id="run-f",
    )
    chapters = [n for n in result.nodes if n.level == 1]
    assert [c.title for c in chapters] == ["第一章 短视频概述", "第二章 平台介绍"]


# ---------------------------------------------------------------------------
# Fix #3 — chunk backfill coverage
# ---------------------------------------------------------------------------


def test_front_matter_blocks_attach_to_first_knowledge_point():
    # Blocks 0-4 = front matter, block 5 = chapter, block 8 = knowledge_point
    cands = [
        _cand(0, 5, "第一章 引论"),
        _cand(1, 8, "一、定义"),
    ]
    cls = [_cls(0, "chapter"), _cls(1, "knowledge_point")]
    result = build_outline_from_classifications(
        cands, cls, _blocks(12),
        root_title="教材",
        build_run_id="run-g",
    )
    kp = next(n for n in result.nodes if n.level == 2)
    # First kp should own blocks b0..b11 (all of them) because it's the
    # only leaf and swallows front-matter + chapter intro.
    assert len(kp.source_block_ids) == 12
    assert "b0" in kp.source_block_ids
    assert "b11" in kp.source_block_ids


def test_chapter_intro_blocks_land_on_first_kp_child():
    # Blocks 0-1 chapter1, 2-4 intro paragraphs, 5 kp_a, 6-7 kp_a body,
    # 8 kp_b, 9 tail
    cands = [
        _cand(0, 0, "第一章 引论"),
        _cand(1, 5, "一、定义"),
        _cand(2, 8, "二、边界"),
    ]
    cls = [_cls(0, "chapter"), _cls(1, "knowledge_point"), _cls(2, "knowledge_point")]
    result = build_outline_from_classifications(
        cands, cls, _blocks(10), root_title="教材", build_run_id="run-h",
    )
    kp_a = next(n for n in result.nodes if n.title == "一、定义")
    kp_b = next(n for n in result.nodes if n.title == "二、边界")
    # kp_a swallows blocks 0-4 (chapter + intro) + 5-7 (own span) = 0..7
    assert set(kp_a.source_block_ids) == {f"b{i}" for i in range(8)}
    # kp_b: 8..9
    assert set(kp_b.source_block_ids) == {"b8", "b9"}


def test_no_chunk_leak_when_multiple_chapters_no_kp_at_end():
    # Last chapter has no knowledge_point — it should itself be a leaf and
    # own the tail blocks.
    cands = [
        _cand(0, 0, "第一章 引论"),
        _cand(1, 3, "一、定义"),
        _cand(2, 6, "第二章 应用"),   # no kp under it
    ]
    cls = [_cls(0, "chapter"), _cls(1, "knowledge_point"), _cls(2, "chapter")]
    result = build_outline_from_classifications(
        cands, cls, _blocks(10), root_title="教材", build_run_id="run-i",
    )
    kp = next(n for n in result.nodes if n.title == "一、定义")
    ch2 = next(n for n in result.nodes if n.title == "第二章 应用")
    # kp gets 0..5 (front + chapter1 intro + own)
    assert set(kp.source_block_ids) == {f"b{i}" for i in range(6)}
    # ch2 is a leaf and gets 6..9
    assert set(ch2.source_block_ids) == {f"b{i}" for i in range(6, 10)}
