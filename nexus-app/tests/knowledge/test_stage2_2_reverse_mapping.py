"""Stage 2.2: each refactored strategy must reverse-map its regex match span
to the heading-/line-bounded subset of blocks via md_char_range.

Inputs are hand-crafted (blocks + body_markdown coordinate system) so the test
isolates the reverse-lookup logic from mineru_converter's offset computation
(which has its own dedicated stability test).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import nexus_app.knowledge.services  # noqa: F401 — register strategies
from nexus_app.enums import ChunkingStrategy, SourceKind
from nexus_app.knowledge.chunk_builder import resolve_blocks_for_span
from nexus_app.knowledge.registry import STRATEGY_REGISTRY


def _kt_config(extra: dict[str, Any] | None = None) -> SimpleNamespace:
    cfg = {
        "min_question_length": 1,
        "min_answer_length": 1,
    }
    if extra:
        cfg.update(extra)
    return SimpleNamespace(
        chunking_config=cfg,
        chunking_strategy=list(ChunkingStrategy)[0].value,
        source_kind=list(SourceKind)[0].value,
        ragflow={"chunk_method": "naive"},
        max_chunks_per_unit=20,
    )


_EMISSION = {"code": "kt", "co_emission_origin": None}


def _make_blocks(specs: list[tuple[str, int, list[float], str, int, int]]):
    """specs: list of (block_id, page, bbox, text, range_start, range_end)."""
    return [
        {
            "block_id": bid,
            "page": page,
            "bbox": bbox,
            "block_type": "paragraph",
            "text": text,
            "md_char_range": [r0, r1],
        }
        for bid, page, bbox, text, r0, r1 in specs
    ]


def _locate_blocks_in_md(
    body_md: str, specs: list[tuple[str, int, list[float], str]],
):
    """Build blocks where each md_char_range is computed by locating the
    block text inside body_md — mirrors what _annotate_md_ranges does in
    real mineru_converter.convert() output."""
    blocks = []
    cursor = 0
    for bid, page, bbox, text in specs:
        idx = body_md.index(text, cursor)
        end = idx + len(text)
        blocks.append({
            "block_id": bid,
            "page": page,
            "bbox": bbox,
            "block_type": "paragraph",
            "text": text,
            "md_char_range": [idx, end],
        })
        cursor = end
    return blocks


# ---------- resolve_blocks_for_span unit checks ----------

def test_resolve_blocks_overlap_single():
    blocks = _make_blocks([
        ("b1", 1, [0, 0, 1, 1], "A", 0, 5),
        ("b2", 1, [0, 0, 1, 1], "B", 7, 12),
        ("b3", 2, [0, 0, 1, 1], "C", 14, 20),
    ])
    hit = resolve_blocks_for_span(blocks, (8, 10))
    assert [b["block_id"] for b in hit] == ["b2"]


def test_resolve_blocks_overlap_multi():
    blocks = _make_blocks([
        ("b1", 1, [0, 0, 1, 1], "A", 0, 5),
        ("b2", 1, [0, 0, 1, 1], "B", 7, 12),
        ("b3", 2, [0, 0, 1, 1], "C", 14, 20),
    ])
    hit = resolve_blocks_for_span(blocks, (4, 15))
    assert [b["block_id"] for b in hit] == ["b1", "b2", "b3"]


def test_resolve_blocks_no_overlap_falls_back():
    blocks = _make_blocks([
        ("b1", 1, [0, 0, 1, 1], "A", 0, 5),
    ])
    # span 100-200 doesn't overlap any block — falls back to all blocks
    hit = resolve_blocks_for_span(blocks, (100, 200))
    assert [b["block_id"] for b in hit] == ["b1"]


def test_resolve_blocks_no_blocks_returns_fallback():
    assert resolve_blocks_for_span(None, (0, 5)) is None
    assert resolve_blocks_for_span([], (0, 5), doc_fallback=None) is None


# ---------- qa_extract ----------

def test_qa_extract_maps_each_pair_to_its_block():
    """Two QA pairs on distinct blocks → each chunk targets only its block."""
    body_md = "问: 什么是 X?\n答: 答案 X.\n问: 什么是 Y?\n答: 答案 Y."
    blocks = _locate_blocks_in_md(body_md, [
        ("b_qa1", 1, [10, 10, 100, 40], "问: 什么是 X?\n答: 答案 X."),
        ("b_qa2", 2, [10, 10, 100, 40], "问: 什么是 Y?\n答: 答案 Y."),
    ])
    strategy = STRATEGY_REGISTRY["qa_extract"]({"min_question_length": 1, "min_answer_length": 1})
    chunks = strategy.chunk(body_md, _EMISSION, _kt_config(), "ref-1", content_blocks=blocks)
    assert len(chunks) == 2
    assert chunks[0].source_block_ids == ["b_qa1"]
    assert chunks[0].locator["page_start"] == 1 and chunks[0].locator["page_end"] == 1
    assert chunks[1].source_block_ids == ["b_qa2"]
    assert chunks[1].locator["page_start"] == 2 and chunks[1].locator["page_end"] == 2


# ---------- process_step_extract ----------

def test_process_step_extract_maps_each_step_to_its_block():
    body_md = "intro paragraph.\n\n步骤1: 启动\n\n步骤2: 入库"
    blocks = _locate_blocks_in_md(body_md, [
        ("b_intro", 1, [10, 10, 100, 30], "intro paragraph."),
        ("b_s1",    1, [10, 40, 100, 70], "步骤1: 启动"),
        ("b_s2",    2, [10, 10, 100, 30], "步骤2: 入库"),
    ])
    strategy = STRATEGY_REGISTRY["process_step_extract"]({"step_indicators": ["步骤"]})
    chunks = strategy.chunk(body_md, _EMISSION, _kt_config(), "ref-2", content_blocks=blocks)
    assert len(chunks) == 2
    assert chunks[0].source_block_ids == ["b_s1"]
    assert chunks[1].source_block_ids == ["b_s2"]


# ---------- indicator_decompose ----------

def test_indicator_decompose_maps_grouped_lines_to_their_blocks():
    body_md = "维度: 服务质量\n指标: 响应时间\n\n维度: 成本\n指标: 单价"
    blocks = _locate_blocks_in_md(body_md, [
        ("b_q", 1, [10, 10, 100, 40], "维度: 服务质量\n指标: 响应时间"),
        ("b_c", 2, [10, 10, 100, 40], "维度: 成本\n指标: 单价"),
    ])
    strategy = STRATEGY_REGISTRY["indicator_decompose"]({"indicator_fields": ["维度", "指标"]})
    chunks = strategy.chunk(body_md, _EMISSION, _kt_config(), "ref-4", content_blocks=blocks)
    assert len(chunks) == 2
    assert chunks[0].source_block_ids == ["b_q"]
    assert chunks[1].source_block_ids == ["b_c"]
    assert chunks[0].locator["page_start"] == 1
    assert chunks[1].locator["page_start"] == 2


# ---------- back-compat ----------

def test_reverse_mapping_strategies_back_compat_no_blocks():
    """Without content_blocks, refactored strategies still yield chunks
    with locator=None (record-pipeline / legacy callers stay safe)."""
    for name, content in [
        ("qa_extract",            "问: q?\n答: a."),
        ("process_step_extract",  "步骤1: 一\n\n步骤2: 二"),
        ("indicator_decompose",   "维度: A\n指标: B"),
    ]:
        cls = STRATEGY_REGISTRY[name]
        cfg = {
            "step_indicators": ["步骤"],
            "indicator_fields": ["维度", "指标"],
        }
        strategy = cls(cfg)
        chunks = strategy.chunk(content, _EMISSION, _kt_config(), "ref-x")
        for c in chunks:
            assert c.locator is None, f"{name}: expected locator=None, got {c.locator}"
            assert c.source_block_ids is None
