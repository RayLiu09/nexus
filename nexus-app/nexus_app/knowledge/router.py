"""Knowledge Pipeline router — dispatches by chunking_mode."""

from __future__ import annotations

from typing import Any

from nexus_app.enums import ChunkType, ChunkingStrategy as ChunkingStrategyEnum, EmbeddingStatus, SourceKind
from nexus_app.knowledge.config_loader import KnowledgeTypeConfig
from nexus_app.knowledge.registry import STRATEGY_REGISTRY
from nexus_app.models import KnowledgeChunk, new_uuid


def route_and_chunk(
    content: str,
    emission: dict[str, Any],
    kt_config: KnowledgeTypeConfig,
    normalized_ref_id: str,
    content_blocks: list[dict[str, Any]] | None = None,
) -> list[KnowledgeChunk]:
    """Route a single emission to the appropriate chunking path.

    Passthrough descriptors do not carry a locator: RAGFlow owns the actual
    chunking and emits its own chunk_ids. Nexus-extract strategies receive
    ``content_blocks`` and decide whether to forward them to ``build_chunk``.
    """
    mode = kt_config.chunking_mode

    if mode == "passthrough_to_ragflow":
        return [_create_passthrough_descriptor(normalized_ref_id, emission, kt_config)]
    elif mode == "nexus_extract":
        return _run_nexus_extract(
            content, emission, kt_config, normalized_ref_id,
            content_blocks=content_blocks,
        )
    else:
        raise ValueError(f"Unknown chunking_mode: {mode}")


def _create_passthrough_descriptor(
    normalized_ref_id: str,
    emission: dict[str, Any],
    kt_config: KnowledgeTypeConfig,
) -> KnowledgeChunk:
    """Create a descriptor chunk for passthrough mode — RAGFlow does the actual chunking."""
    return KnowledgeChunk(
        id=new_uuid(),
        normalized_ref_id=normalized_ref_id,
        knowledge_type_code=emission["code"],
        chunk_type=ChunkType.PASSTHROUGH_DESCRIPTOR,
        chunking_strategy=ChunkingStrategyEnum.PASSTHROUGH_TO_RAGFLOW,
        source_kind=SourceKind(kt_config.source_kind),
        chunk_index=0,
        content="",
        chunk_metadata={
            "chunking_config_snapshot": kt_config.ragflow.get("parser_config", {}),
            "co_emission_origin": emission.get("co_emission_origin"),
            "ragflow_doc_id": None,
            "ragflow_chunk_ids": [],
        },
        co_emission_origin=emission.get("co_emission_origin"),
        ragflow_chunk_method=kt_config.ragflow.get("chunk_method"),
        embedding_status=EmbeddingStatus.PENDING,
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
