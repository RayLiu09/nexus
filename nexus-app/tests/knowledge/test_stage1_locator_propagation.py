"""Stage 1: every strategy must propagate content_blocks to chunk.locator.

Locks down the chunking-pipeline → build_chunk path so that Stage 2.x precision
improvements can be added per strategy without losing the document-level fallback.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import nexus_app.knowledge.services  # registers all strategies
from nexus_app.enums import ChunkingStrategy, SourceKind
from nexus_app.knowledge.registry import STRATEGY_REGISTRY


def _fake_kt_config(extra_cfg: dict[str, Any] | None = None) -> SimpleNamespace:
    cfg = {
        "min_question_length": 1,
        "min_answer_length": 1,
    }
    if extra_cfg:
        cfg.update(extra_cfg)
    return SimpleNamespace(
        chunking_config=cfg,
        chunking_strategy=list(ChunkingStrategy)[0].value,
        source_kind=list(SourceKind)[0].value,
        ragflow={"chunk_method": "naive"},
        max_chunks_per_unit=20,
    )


_EMISSION = {"code": "kt", "co_emission_origin": None}


def test_all_strategies_attach_locator_when_blocks_provided():
    """Every nexus_extract strategy must populate chunk.locator when caller
    supplies content_blocks, even if precise sub-window mapping is not yet
    implemented (Stage 2.x). Doc-level fallback is the contract floor."""
    blocks = [
        {"block_id": "b1", "page": 1, "bbox": [10, 20, 100, 50], "block_type": "paragraph"},
        {"block_id": "b2", "page": 2, "bbox": [10, 60, 100, 90], "block_type": "paragraph"},
    ]
    # Generic content that each strategy can at least produce one chunk from.
    content = "问: 什么是 NEXUS?\n答: 一个企业数据知识平台。\n\n步骤1: 启动\n步骤2: 入库\n"

    for name, cls in STRATEGY_REGISTRY.items():
        strategy = cls({})
        chunks = strategy.chunk(
            content, _EMISSION, _fake_kt_config(), "ref-1",
            content_blocks=blocks,
        )
        if not chunks:
            # Some strategies may produce zero chunks for this generic input;
            # that's acceptable. They still must not crash.
            continue
        for c in chunks:
            assert c.locator is not None, f"{name}: locator missing"
            assert c.locator["page_start"] == 1
            assert c.locator["page_end"] == 2
            assert c.locator["bbox_union"] is None  # cross-page
            assert c.source_block_ids == ["b1", "b2"]


def test_back_compat_no_blocks_means_no_locator():
    """Legacy callers passing no content_blocks (record pipeline, old code)
    still get chunks; locator stays null per record-type contract."""
    content = "问: x?\n答: y."
    for name, cls in STRATEGY_REGISTRY.items():
        strategy = cls({})
        chunks = strategy.chunk(content, _EMISSION, _fake_kt_config(), "ref-2")
        for c in chunks:
            assert c.locator is None
            assert c.source_block_ids is None
