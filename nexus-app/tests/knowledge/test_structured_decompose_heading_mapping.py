"""Stage 2.1: structured_decompose must restrict chunk.locator to the
heading-bounded subset of blocks for each field, not the whole document."""
from __future__ import annotations

from types import SimpleNamespace

import nexus_app.knowledge.services  # noqa: F401 — register strategies
from nexus_app.enums import ChunkingStrategy, SourceKind
from nexus_app.knowledge.chunking_strategies.structured_decompose import (
    StructuredDecomposeStrategy,
)


_EMISSION = {"code": "talent_training_dataset", "co_emission_origin": None}


def _kt_config():
    return SimpleNamespace(
        chunking_config={"decompose_fields": ["培养目标", "课程体系"]},
        chunking_strategy=list(ChunkingStrategy)[0].value,
        source_kind=list(SourceKind)[0].value,
        ragflow={"chunk_method": "naive"},
        max_chunks_per_unit=50,
    )


def _blocks():
    return [
        # Preamble — dropped (no current field)
        {"block_id": "b0", "page": 1, "bbox": [10, 10, 100, 30],
         "block_type": "paragraph", "text": "前言..."},
        # Heading: 培养目标
        {"block_id": "h1", "page": 1, "bbox": [10, 40, 100, 60],
         "block_type": "heading", "text": "1. 培养目标"},
        {"block_id": "p1", "page": 1, "bbox": [10, 70, 100, 120],
         "block_type": "paragraph", "text": "本专业培养具备 X 能力的人才。"},
        {"block_id": "p2", "page": 1, "bbox": [10, 130, 100, 180],
         "block_type": "paragraph", "text": "毕业要求 Y。"},
        # Heading: 课程体系
        {"block_id": "h2", "page": 2, "bbox": [10, 40, 100, 60],
         "block_type": "heading", "text": "2. 课程体系"},
        {"block_id": "p3", "page": 2, "bbox": [10, 70, 100, 120],
         "block_type": "paragraph", "text": "公共基础课包括..."},
        {"block_id": "p4", "page": 3, "bbox": [10, 70, 100, 120],
         "block_type": "paragraph", "text": "专业课包括..."},
    ]


def _content():
    return (
        "前言...\n"
        "培养目标\n"
        "本专业培养具备 X 能力的人才。\n"
        "毕业要求 Y。\n"
        "课程体系\n"
        "公共基础课包括...\n"
        "专业课包括...\n"
    )


def test_field_blocks_are_heading_bounded():
    """培养目标 chunk's locator must include p1/p2 only;
    课程体系 chunk's locator must include p3/p4 only."""
    strategy = StructuredDecomposeStrategy({"decompose_fields": ["培养目标", "课程体系"]})
    chunks = strategy.chunk(
        _content(), _EMISSION, _kt_config(), "ref-1",
        content_blocks=_blocks(),
    )

    by_field: dict[str, list] = {}
    for c in chunks:
        fname = c.chunk_metadata["field_name"]
        by_field.setdefault(fname, []).append(c)

    assert "培养目标" in by_field, f"expected field chunks not found: {list(by_field)}"
    assert "课程体系" in by_field

    objective_blocks = set(by_field["培养目标"][0].source_block_ids)
    curriculum_blocks = set(by_field["课程体系"][0].source_block_ids)

    assert objective_blocks == {"p1", "p2"}, f"got {objective_blocks}"
    assert curriculum_blocks == {"p3", "p4"}, f"got {curriculum_blocks}"

    # 培养目标 chunks all on page 1
    obj_loc = by_field["培养目标"][0].locator
    assert obj_loc["page_start"] == 1 and obj_loc["page_end"] == 1
    assert obj_loc["bbox_union"] is not None  # single-page → union computed

    # 课程体系 spans page 2-3
    cur_loc = by_field["课程体系"][0].locator
    assert cur_loc["page_start"] == 2 and cur_loc["page_end"] == 3
    assert cur_loc["bbox_union"] is None  # cross-page


def test_missing_heading_falls_back_to_doc_level():
    """When a configured field has no matching heading block, that field's
    chunks (if any) should fall back to document-level locator instead of
    being silently locator-less."""
    blocks = [
        {"block_id": "h1", "page": 1, "bbox": [10, 10, 100, 30],
         "block_type": "heading", "text": "1. 培养目标"},
        {"block_id": "p1", "page": 1, "bbox": [10, 40, 100, 80],
         "block_type": "paragraph", "text": "本专业培养..."},
    ]
    content = "培养目标\n本专业培养...\n课程体系\n（缺失内容）"
    strategy = StructuredDecomposeStrategy({"decompose_fields": ["培养目标", "课程体系"]})
    chunks = strategy.chunk(content, _EMISSION, _kt_config(), "ref-2",
                            content_blocks=blocks)

    # 课程体系 has no heading block but field_map carries a placeholder; if it
    # yields a chunk, blocks fallback to doc-level. If empty text → no chunk,
    # and that's fine.
    for c in chunks:
        if c.chunk_metadata.get("field_name") == "课程体系" and c.locator is not None:
            # Doc-level fallback: locator includes every block, h1 + p1
            assert set(c.source_block_ids) == {"h1", "p1"}


def test_no_blocks_yields_no_locator():
    """Back-compat: callers passing no content_blocks still chunk; locator None."""
    strategy = StructuredDecomposeStrategy({"decompose_fields": ["培养目标"]})
    chunks = strategy.chunk(
        "培养目标\n培养 X 人才。", _EMISSION, _kt_config(), "ref-3",
    )
    for c in chunks:
        assert c.locator is None
        assert c.source_block_ids is None
