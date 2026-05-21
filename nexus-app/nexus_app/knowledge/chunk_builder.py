"""Common chunk construction utility."""

from __future__ import annotations

from typing import Any

from nexus_app.enums import ChunkType, ChunkingStrategy, EmbeddingStatus, SourceKind
from nexus_app.models import KnowledgeChunk, new_uuid


def build_chunk(
    normalized_ref_id: str,
    emission: dict[str, Any],
    kt_config: Any,
    *,
    chunk_type: ChunkType,
    index: int,
    content: str,
    extra_metadata: dict[str, Any] | None = None,
) -> KnowledgeChunk:
    """Construct a KnowledgeChunk with standard fields populated."""
    meta: dict[str, Any] = {
        "chunking_config_snapshot": kt_config.chunking_config,
        "co_emission_origin": emission.get("co_emission_origin"),
    }
    if extra_metadata:
        meta.update(extra_metadata)

    return KnowledgeChunk(
        id=new_uuid(),
        normalized_ref_id=normalized_ref_id,
        knowledge_type_code=emission["code"],
        chunk_type=chunk_type,
        chunking_strategy=ChunkingStrategy(kt_config.chunking_strategy),
        source_kind=SourceKind(kt_config.source_kind),
        chunk_index=index,
        content=content,
        chunk_metadata=meta,
        co_emission_origin=emission.get("co_emission_origin"),
        ragflow_chunk_method=kt_config.ragflow.get("chunk_method"),
        embedding_status=EmbeddingStatus.PENDING,
    )
