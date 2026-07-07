"""Resolve pgvector logical collections and metadata projections."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from nexus_app.models import KnowledgeChunk, NormalizedAssetRef

DEFAULT_METADATA_SCHEMA_VERSION = "v1"


@dataclass(frozen=True)
class CollectionResolution:
    collection_key: str
    asset_domain_type: str
    normalized_type: str
    embedding_provider: str
    embedding_model: str
    embedding_dimension: int
    distance_metric: str
    metadata_schema_version: str = DEFAULT_METADATA_SCHEMA_VERSION


@dataclass(frozen=True)
class VectorProjection:
    columns: dict[str, Any]
    metadata: dict[str, Any]


def resolve_collection(
    normalized_ref: NormalizedAssetRef,
    chunk: KnowledgeChunk,
    *,
    embedding_model_alias: str,
    embedding_dimension: int,
    distance_metric: str = "cosine",
    metadata_schema_version: str = DEFAULT_METADATA_SCHEMA_VERSION,
) -> CollectionResolution:
    asset_domain_type = resolve_asset_domain_type(normalized_ref, chunk)
    normalized_type = _enum_value(normalized_ref.normalized_type)
    model_key = _slugify_model_alias(embedding_model_alias)
    collection_key = ".".join(
        [
            asset_domain_type,
            normalized_type,
            model_key,
            metadata_schema_version,
        ]
    )
    return CollectionResolution(
        collection_key=collection_key,
        asset_domain_type=asset_domain_type,
        normalized_type=normalized_type,
        embedding_provider="litellm",
        embedding_model=embedding_model_alias,
        embedding_dimension=embedding_dimension,
        distance_metric=distance_metric,
        metadata_schema_version=metadata_schema_version,
    )


def resolve_asset_domain_type(normalized_ref: NormalizedAssetRef, chunk: KnowledgeChunk) -> str:
    governance = normalized_ref.governance or {}
    metadata = normalized_ref.metadata_summary or {}
    chunk_metadata = chunk.chunk_metadata or {}
    candidates = [
        governance.get("classification"),
        governance.get("asset_domain_type"),
        governance.get("domain_type"),
        metadata.get("classification"),
        metadata.get("asset_domain_type"),
        metadata.get("domain_type"),
        metadata.get("domain_profile"),
        chunk_metadata.get("domain_profile"),
        chunk.knowledge_type_code,
    ]
    for candidate in candidates:
        normalized = _normalize_token(candidate)
        if normalized:
            return normalized
    return "generic"


def build_vector_projection(
    normalized_ref: NormalizedAssetRef,
    chunk: KnowledgeChunk,
    resolution: CollectionResolution,
    *,
    embedding: list[float],
    asset_id: str | None = None,
    asset_version_id: str | None = None,
    trace_id: str | None = None,
) -> VectorProjection:
    ref_version = getattr(normalized_ref, "version", None)
    resolved_asset_version_id = asset_version_id or normalized_ref.version_id
    resolved_asset_id = asset_id or getattr(ref_version, "asset_id", None)
    if not resolved_asset_id:
        raise ValueError("asset_id is required when normalized_ref.version is not loaded")

    metadata = build_vector_metadata(
        normalized_ref,
        chunk,
        resolution,
        asset_id=resolved_asset_id,
        asset_version_id=resolved_asset_version_id,
    )
    columns = {
        "collection_key": resolution.collection_key,
        "chunk_id": chunk.id,
        "normalized_ref_id": normalized_ref.id,
        "asset_id": resolved_asset_id,
        "asset_version_id": resolved_asset_version_id,
        "asset_domain_type": resolution.asset_domain_type,
        "knowledge_type_code": chunk.knowledge_type_code,
        "domain_profile": metadata["chunk"].get("domain_profile")
        or metadata["normalized_ref"].get("domain_profile"),
        "normalized_type": resolution.normalized_type,
        "content_type": normalized_ref.content_type,
        "source_type": normalized_ref.source_type,
        "language": normalized_ref.language,
        "chunk_type": _enum_value(chunk.chunk_type),
        "chunking_strategy": _enum_value(chunk.chunking_strategy),
        "embedding_provider": resolution.embedding_provider,
        "embedding_model": resolution.embedding_model,
        "embedding_dimension": resolution.embedding_dimension,
        "distance_metric": resolution.distance_metric,
        "metadata_schema_version": resolution.metadata_schema_version,
        "embedding": embedding,
        "embedding_hash": _hash_floats(embedding),
        "content_hash": _hash_text(chunk.content or ""),
        "vector_metadata": metadata,
        "trace_id": trace_id,
    }
    return VectorProjection(columns=columns, metadata=metadata)


def build_vector_metadata(
    normalized_ref: NormalizedAssetRef,
    chunk: KnowledgeChunk,
    resolution: CollectionResolution,
    *,
    asset_id: str,
    asset_version_id: str,
) -> dict[str, Any]:
    governance = normalized_ref.governance or {}
    quality = normalized_ref.quality or {}
    metadata = normalized_ref.metadata_summary or {}
    chunk_metadata = chunk.chunk_metadata or {}
    locator = chunk.locator or {}

    return {
        "schema_version": resolution.metadata_schema_version,
        "asset": {
            "asset_id": asset_id,
            "asset_version_id": asset_version_id,
            "title": normalized_ref.title,
            "classification": governance.get("classification") or metadata.get("classification"),
            "level": governance.get("level") or governance.get("sensitivity_level"),
            "tags": governance.get("tags") or metadata.get("tags") or [],
            "org_scope": governance.get("org_scope") or metadata.get("org_scope") or [],
        },
        "normalized_ref": {
            "normalized_ref_id": normalized_ref.id,
            "normalized_type": _enum_value(normalized_ref.normalized_type),
            "source_type": normalized_ref.source_type,
            "content_type": normalized_ref.content_type,
            "title": normalized_ref.title,
            "language": normalized_ref.language,
            "governance": governance,
            "quality": quality,
            "lineage": normalized_ref.lineage or {},
            "domain_profile": metadata.get("domain_profile"),
        },
        "chunk": {
            "chunk_id": chunk.id,
            "knowledge_type_code": chunk.knowledge_type_code,
            "chunk_index": chunk.chunk_index,
            "chunk_type": _enum_value(chunk.chunk_type),
            "chunking_strategy": _enum_value(chunk.chunking_strategy),
            "heading_path": chunk_metadata.get("heading_path")
            or chunk_metadata.get("section_path")
            or [],
            "domain_model": chunk_metadata.get("domain_model"),
            "domain_profile": chunk_metadata.get("domain_profile"),
            "section_profile": chunk_metadata.get("section_processing_profile")
            or chunk_metadata.get("section_profile"),
            "source_block_ids": chunk.source_block_ids or [],
        },
        "locator": {
            "page_start": locator.get("page_start"),
            "page_end": locator.get("page_end"),
        },
        "index": {
            "embedding_provider": resolution.embedding_provider,
            "embedding_model": resolution.embedding_model,
            "embedding_dimension": resolution.embedding_dimension,
            "distance_metric": resolution.distance_metric,
            "collection_key": resolution.collection_key,
            "asset_domain_type": resolution.asset_domain_type,
            "metadata_schema_version": resolution.metadata_schema_version,
        },
    }


def _enum_value(value: Any) -> str:
    return getattr(value, "value", value)


def _normalize_token(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).strip().lower()
    if not token:
        return None
    token = re.sub(r"[^a-z0-9_]+", "_", token)
    token = re.sub(r"_+", "_", token).strip("_")
    return token or None


def _slugify_model_alias(value: str) -> str:
    token = _normalize_token(value)
    return token or "embedding_model"


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_floats(values: list[float]) -> str:
    payload = ",".join(f"{float(value):.8f}" for value in values)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
