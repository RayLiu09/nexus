"""Stage 2.4: graph_extract carries primary + evidence blocks for each triple.

Concept-level chunks lack a single block anchor; the locator should aggregate
the primary extraction block (the line where the relation was stated) plus
the blocks that independently mention either concept (the "supporting set").
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import nexus_app.knowledge.services  # noqa: F401 — register strategies
from nexus_app.enums import ChunkingStrategy, SourceKind
from nexus_app.knowledge.registry import STRATEGY_REGISTRY


_EMISSION = {"code": "kg_corpus", "co_emission_origin": None}


def _kt_config():
    return SimpleNamespace(
        chunking_config={},
        chunking_strategy=list(ChunkingStrategy)[0].value,
        source_kind=list(SourceKind)[0].value,
        ragflow={"chunk_method": "knowledge_graph"},
        max_chunks_per_unit=50,
    )


def _locate_blocks(body_md: str, specs: list[tuple[str, int, str]]):
    """specs: (block_id, page, text)."""
    blocks = []
    cursor = 0
    for bid, page, text in specs:
        idx = body_md.index(text, cursor)
        end = idx + len(text)
        blocks.append({
            "block_id": bid,
            "page": page,
            "bbox": [0, 0, 100, 50],
            "block_type": "paragraph",
            "text": text,
            "md_char_range": [idx, end],
        })
        cursor = end
    return blocks


def test_graph_extract_primary_block_is_extraction_line():
    """The primary block for a triple is the one whose md_char_range covers
    the extraction line — not any block that merely mentions the concept."""
    body_md = (
        "数据结构 包含 数组\n"
        "其他主题的段落。\n"
        "算法基础内容。"
    )
    blocks = _locate_blocks(body_md, [
        ("b_rel", 1, "数据结构 包含 数组"),
        ("b_other", 2, "其他主题的段落。"),
        ("b_alg", 3, "算法基础内容。"),
    ])
    strategy = STRATEGY_REGISTRY["graph_extract"]({})
    chunks = strategy.chunk(body_md, _EMISSION, _kt_config(), "ref-1",
                            content_blocks=blocks)
    assert len(chunks) == 1
    c = chunks[0]
    # The extraction line maps to b_rel
    assert c.chunk_metadata["primary_block_ids"] == ["b_rel"]
    # No other blocks mention "数据结构" or "数组" — evidence empty
    assert c.chunk_metadata["evidence_block_ids"] == []
    assert c.source_block_ids == ["b_rel"]


def test_graph_extract_collects_evidence_blocks_for_concepts():
    """When other blocks mention subject or object, they become evidence."""
    body_md = (
        "数据结构 包含 数组\n"
        "数据结构是计算机科学的基础。\n"
        "数组是一种线性结构。\n"
        "无关内容段落。"
    )
    blocks = _locate_blocks(body_md, [
        ("b_rel", 1, "数据结构 包含 数组"),
        ("b_sub_evidence", 1, "数据结构是计算机科学的基础。"),
        ("b_obj_evidence", 2, "数组是一种线性结构。"),
        ("b_noise", 3, "无关内容段落。"),
    ])
    strategy = STRATEGY_REGISTRY["graph_extract"]({})
    chunks = strategy.chunk(body_md, _EMISSION, _kt_config(), "ref-2",
                            content_blocks=blocks)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.chunk_metadata["primary_block_ids"] == ["b_rel"]
    # Both evidence blocks present, primary excluded
    assert set(c.chunk_metadata["evidence_block_ids"]) == {
        "b_sub_evidence", "b_obj_evidence",
    }
    # source_blocks is the deduped union
    assert set(c.source_block_ids) == {
        "b_rel", "b_sub_evidence", "b_obj_evidence",
    }
    # b_noise does not mention either concept → excluded
    assert "b_noise" not in c.source_block_ids


def test_graph_extract_caps_evidence_per_concept():
    """Common terms must not cause runaway evidence collection."""
    body_md_lines = ["A 包含 B"] + [f"提到 A 的第{i}段。" for i in range(10)]
    body_md = "\n".join(body_md_lines)
    specs = [("b_rel", 1, "A 包含 B")]
    specs.extend(
        (f"b_a_{i}", 1, f"提到 A 的第{i}段。") for i in range(10)
    )
    blocks = _locate_blocks(body_md, specs)

    strategy = STRATEGY_REGISTRY["graph_extract"]({})
    chunks = strategy.chunk(body_md, _EMISSION, _kt_config(), "ref-3",
                            content_blocks=blocks)
    assert len(chunks) == 1
    # Cap is 5 per concept (subject="A"); object="B" has zero evidence.
    assert len(chunks[0].chunk_metadata["evidence_block_ids"]) == 5


def test_graph_extract_evidence_deduped_across_subject_and_object():
    """A block mentioning both subject and object must appear once in the
    aggregated evidence list."""
    body_md = (
        "A 包含 B\n"
        "A 与 B 共同出现的段落。"
    )
    blocks = _locate_blocks(body_md, [
        ("b_rel", 1, "A 包含 B"),
        ("b_both", 1, "A 与 B 共同出现的段落。"),
    ])
    strategy = STRATEGY_REGISTRY["graph_extract"]({})
    chunks = strategy.chunk(body_md, _EMISSION, _kt_config(), "ref-4",
                            content_blocks=blocks)
    assert chunks
    assert chunks[0].chunk_metadata["evidence_block_ids"] == ["b_both"]
    assert chunks[0].source_block_ids == ["b_rel", "b_both"]


def test_graph_extract_back_compat_no_blocks():
    """Without content_blocks the strategy must still yield triples, with
    locator None and empty primary/evidence partition metadata."""
    strategy = STRATEGY_REGISTRY["graph_extract"]({})
    chunks = strategy.chunk("A 包含 B", _EMISSION, _kt_config(), "ref-5")
    assert len(chunks) == 1
    c = chunks[0]
    assert c.locator is None
    assert c.source_block_ids is None
    assert c.chunk_metadata["primary_block_ids"] == []
    assert c.chunk_metadata["evidence_block_ids"] == []


def test_graph_extract_no_md_char_range_falls_back_to_doc_level():
    """If blocks lack md_char_range (e.g. legacy normalize output), the
    strategy must still produce chunks. Primary will be empty (no overlap);
    evidence still works because it relies on text mentions, not offsets."""
    body_md = "A 包含 B\n关于 A 的另一段。"
    blocks = [
        {"block_id": "b_rel", "page": 1, "bbox": [0, 0, 1, 1],
         "block_type": "paragraph", "text": "A 包含 B"},
        {"block_id": "b_a", "page": 1, "bbox": [0, 0, 1, 1],
         "block_type": "paragraph", "text": "关于 A 的另一段。"},
    ]
    strategy = STRATEGY_REGISTRY["graph_extract"]({})
    chunks = strategy.chunk(body_md, _EMISSION, _kt_config(), "ref-6",
                            content_blocks=blocks)
    assert chunks
    # Without md_char_range, primary is empty; evidence picks up the mention.
    c = chunks[0]
    assert c.chunk_metadata["primary_block_ids"] == []
    assert "b_a" in c.chunk_metadata["evidence_block_ids"]
    # source_blocks remains non-empty (evidence carries it)
    assert "b_a" in c.source_block_ids
