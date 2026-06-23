"""Knowledge Pipeline router — dispatches by chunking_mode.

Nexus-owned semantic chunking is a first-class path: ``nexus_semantic`` runs
``semantic_repack`` over normalized blocks and emits N ``SEMANTIC_BLOCK`` rows,
each carrying md_char_range / md_spans / heading_path / anchor_role for source
preview. The legacy ``passthrough_to_ragflow`` mode is accepted only as a
backward-compatible alias for old configs; RAGFlow is not the owner of chunk
construction in this path.
"""

from __future__ import annotations

from typing import Any

from nexus_app.enums import ChunkType, ChunkingStrategy
from nexus_app.knowledge.chunk_builder import build_chunk
from nexus_app.knowledge.config_loader import KnowledgeTypeConfig
from nexus_app.knowledge.registry import STRATEGY_REGISTRY
from nexus_app.knowledge.semantic_repack import repack as semantic_repack
from nexus_app.models import KnowledgeChunk


def route_and_chunk(
    content: str,
    emission: dict[str, Any],
    kt_config: KnowledgeTypeConfig,
    normalized_ref_id: str,
    content_blocks: list[dict[str, Any]] | None = None,
) -> list[KnowledgeChunk]:
    """Route a single emission to the appropriate chunking path.

    - ``nexus_semantic`` → semantic_repack → N ``SEMANTIC_BLOCK`` chunks
      (Nexus-owned segmentation).
    - legacy ``passthrough_to_ragflow`` is treated as the same semantic path.
    - ``nexus_extract`` → registered structured strategy (qa_extract,
      indicator_decompose, etc.).
    """
    mode = kt_config.chunking_mode

    if mode in {"nexus_semantic", "passthrough_to_ragflow"}:
        return _run_semantic_repack(
            content, emission, kt_config, normalized_ref_id,
            content_blocks=content_blocks,
        )
    elif mode == "nexus_extract":
        return _run_nexus_extract(
            content, emission, kt_config, normalized_ref_id,
            content_blocks=content_blocks,
        )
    else:
        raise ValueError(f"Unknown chunking_mode: {mode}")


def _run_semantic_repack(
    content: str,
    emission: dict[str, Any],
    kt_config: KnowledgeTypeConfig,
    normalized_ref_id: str,
    content_blocks: list[dict[str, Any]] | None = None,
) -> list[KnowledgeChunk]:
    """Nexus semantic path: blocks → semantic_repack → N SEMANTIC_BLOCK chunks.

    Falls back to a single empty descriptor only when block-level data is not
    provided (e.g. legacy fake adapter outputs). Real document pipelines should
    provide normalized blocks and produce per-unit chunks.
    """
    if not content_blocks:
        return [_legacy_descriptor(normalized_ref_id, emission, kt_config)]

    units = semantic_repack(content_blocks, body_markdown=content)
    if not units:
        # Nothing survived the cleaning pipeline. Surface a single legacy
        # descriptor so the asset still has a visible chunking trace instead
        # of being silently dropped.
        return [_legacy_descriptor(normalized_ref_id, emission, kt_config)]

    chunks: list[KnowledgeChunk] = []
    for i, unit in enumerate(units):
        chunks.append(
            build_chunk(
                normalized_ref_id=normalized_ref_id,
                emission=emission,
                kt_config=kt_config,
                chunk_type=ChunkType.SEMANTIC_BLOCK,
                chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK,
                index=i,
                content=unit["content"],
                source_blocks=unit["source_blocks"],
                heading_path=unit.get("heading_path"),
                md_spans=unit.get("md_spans"),
                anchor_role=unit.get("anchor_role"),
                caption=unit.get("caption"),
                extra_metadata=unit.get("metadata"),
            )
        )
    return chunks


def _legacy_descriptor(
    normalized_ref_id: str,
    emission: dict[str, Any],
    kt_config: KnowledgeTypeConfig,
) -> KnowledgeChunk:
    """Fallback used only when no block-level data is available."""
    return build_chunk(
        normalized_ref_id=normalized_ref_id,
        emission=emission,
        kt_config=kt_config,
        chunk_type=ChunkType.PASSTHROUGH_DESCRIPTOR,
        chunking_strategy=ChunkingStrategy.PASSTHROUGH_TO_RAGFLOW,
        index=0,
        content="",
        extra_metadata={
            "ragflow_doc_id": None,
            "ragflow_chunk_ids": [],
        },
    )


def _run_nexus_extract(
    content: str,
    emission: dict[str, Any],
    kt_config: KnowledgeTypeConfig,
    normalized_ref_id: str,
    content_blocks: list[dict[str, Any]] | None = None,
) -> list[KnowledgeChunk]:
    """Run a registered chunking strategy for nexus_extract mode."""
    strategy_name = kt_config.chunking_strategy
    if strategy_name not in STRATEGY_REGISTRY:
        raise ValueError(
            f"Strategy '{strategy_name}' not registered. "
            f"Available: {list(STRATEGY_REGISTRY.keys())}"
        )
    strategy_cls = STRATEGY_REGISTRY[strategy_name]
    strategy = strategy_cls(kt_config.chunking_config)
    return strategy.chunk(
        content, emission, kt_config, normalized_ref_id,
        content_blocks=content_blocks,
    )
