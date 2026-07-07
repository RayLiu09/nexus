"""pgvector indexing service for NEXUS-owned knowledge chunks."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app.config import Settings, get_settings
from nexus_app.enums import EmbeddingStatus
from nexus_app.index.collection_resolver import (
    CollectionResolution,
    build_vector_projection,
    resolve_collection,
)
from nexus_app.index.embedding_client import EmbeddingClientProtocol, create_embedding_client
from nexus_app.models import (
    AssetVersion,
    KnowledgeChunk,
    KnowledgeEmbeddingPgvector,
    NormalizedAssetRef,
    VectorCollection,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PgvectorIndexResult:
    collection_count: int
    embedded_chunk_count: int
    failed_chunk_count: int
    collection_keys: list[str]


def index_chunks_pgvector(
    session: Session,
    normalized_ref: NormalizedAssetRef,
    chunks: Sequence[KnowledgeChunk],
    *,
    settings: Settings | None = None,
    embedding_client: EmbeddingClientProtocol | None = None,
    trace_id: str | None = None,
) -> PgvectorIndexResult:
    if not chunks:
        return PgvectorIndexResult(
            collection_count=0,
            embedded_chunk_count=0,
            failed_chunk_count=0,
            collection_keys=[],
        )

    current_settings = settings or get_settings()
    client = embedding_client or create_embedding_client(current_settings)
    model_alias = current_settings.effective_embedding_model_alias
    dimension = current_settings.default_embedding_dimension
    distance_metric = current_settings.default_embedding_distance_metric
    batch_size = max(1, current_settings.embedding_batch_size)
    version = _load_version(session, normalized_ref)

    chunks_by_collection: dict[str, tuple[CollectionResolution, list[KnowledgeChunk]]] = {}
    for chunk in chunks:
        resolution = resolve_collection(
            normalized_ref,
            chunk,
            embedding_model_alias=model_alias,
            embedding_dimension=dimension,
            distance_metric=distance_metric,
        )
        entry = chunks_by_collection.setdefault(resolution.collection_key, (resolution, []))
        entry[1].append(chunk)

    embedded_count = 0
    failed_count = 0
    collection_keys: list[str] = []

    for resolution, collection_chunks in chunks_by_collection.values():
        collection = _get_or_create_collection(session, resolution, trace_id=trace_id)
        collection_keys.append(collection.collection_key)
        for batch in _chunked(collection_chunks, batch_size):
            try:
                embedding_result = client.embed_texts(
                    [chunk.content or "" for chunk in batch],
                    model_alias=resolution.embedding_model,
                    expected_dimension=resolution.embedding_dimension,
                )
                for chunk, vector in zip(batch, embedding_result.vectors, strict=True):
                    _upsert_embedding_row(
                        session,
                        normalized_ref,
                        chunk,
                        collection,
                        resolution,
                        vector,
                        asset_id=version.asset_id,
                        asset_version_id=version.id,
                        trace_id=trace_id,
                    )
                    chunk.embedding_status = EmbeddingStatus.EMBEDDED
                    embedded_count += 1
            except Exception:
                failed_count += len(batch)
                for chunk in batch:
                    chunk.embedding_status = EmbeddingStatus.FAILED
                logger.exception(
                    "pgvector embedding batch failed normalized_ref_id=%s collection_key=%s count=%s",
                    normalized_ref.id,
                    resolution.collection_key,
                    len(batch),
                )
                raise

    session.flush()
    return PgvectorIndexResult(
        collection_count=len(collection_keys),
        embedded_chunk_count=embedded_count,
        failed_chunk_count=failed_count,
        collection_keys=collection_keys,
    )


def _load_version(session: Session, normalized_ref: NormalizedAssetRef) -> AssetVersion:
    version = session.get(AssetVersion, normalized_ref.version_id)
    if version is None:
        raise ValueError(f"asset version not found for normalized_ref_id={normalized_ref.id}")
    return version


def _get_or_create_collection(
    session: Session,
    resolution: CollectionResolution,
    *,
    trace_id: str | None,
) -> VectorCollection:
    collection = session.scalar(
        select(VectorCollection).where(
            VectorCollection.collection_key == resolution.collection_key
        )
    )
    if collection is not None:
        return collection
    collection = VectorCollection(
        collection_key=resolution.collection_key,
        asset_domain_type=resolution.asset_domain_type,
        normalized_type=resolution.normalized_type,
        embedding_provider=resolution.embedding_provider,
        embedding_model=resolution.embedding_model,
        embedding_dimension=resolution.embedding_dimension,
        distance_metric=resolution.distance_metric,
        metadata_schema_version=resolution.metadata_schema_version,
        collection_metadata={
            "asset_domain_type": resolution.asset_domain_type,
            "normalized_type": resolution.normalized_type,
            "embedding_provider": resolution.embedding_provider,
            "embedding_model": resolution.embedding_model,
            "embedding_dimension": resolution.embedding_dimension,
            "distance_metric": resolution.distance_metric,
            "metadata_schema_version": resolution.metadata_schema_version,
        },
        trace_id=trace_id,
    )
    session.add(collection)
    session.flush()
    return collection


def _upsert_embedding_row(
    session: Session,
    normalized_ref: NormalizedAssetRef,
    chunk: KnowledgeChunk,
    collection: VectorCollection,
    resolution: CollectionResolution,
    embedding: list[float],
    *,
    asset_id: str,
    asset_version_id: str,
    trace_id: str | None,
) -> KnowledgeEmbeddingPgvector:
    projection = build_vector_projection(
        normalized_ref,
        chunk,
        resolution,
        embedding=embedding,
        asset_id=asset_id,
        asset_version_id=asset_version_id,
        trace_id=trace_id,
    )
    row = session.scalar(
        select(KnowledgeEmbeddingPgvector).where(
            KnowledgeEmbeddingPgvector.collection_id == collection.id,
            KnowledgeEmbeddingPgvector.chunk_id == chunk.id,
        )
    )
    if row is None:
        row = KnowledgeEmbeddingPgvector(
            collection_id=collection.id,
            **projection.columns,
        )
        session.add(row)
        return row

    for key, value in projection.columns.items():
        setattr(row, key, value)
    row.collection_id = collection.id
    return row


def _chunked(items: Sequence[KnowledgeChunk], batch_size: int) -> list[Sequence[KnowledgeChunk]]:
    return [items[index:index + batch_size] for index in range(0, len(items), batch_size)]
