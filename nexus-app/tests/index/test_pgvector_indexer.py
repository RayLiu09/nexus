from __future__ import annotations

import pytest
from sqlalchemy import func, select

from nexus_app import models
from nexus_app.config import Settings
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    ChunkingStrategy,
    ChunkType,
    DataSourceType,
    EmbeddingStatus,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
    SourceKind,
)
from nexus_app.index.embedding_client import EmbeddingClientError, FakeEmbeddingClient
from nexus_app.index.pgvector_indexer import index_chunks_pgvector


def _settings() -> Settings:
    return Settings(
        DEFAULT_EMBEDDING_MODEL="bge-m3:latest",
        DEFAULT_EMBEDDING_DIMENSION=8,
        EMBEDDING_BATCH_SIZE=2,
    )


def _seed_ref_and_chunks(session, *, chunk_count: int = 2):
    ds = models.DataSource(
        id="ds-indexer",
        code="ds-indexer",
        name="pgvector indexer source",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="batch-indexer",
        data_source_id=ds.id,
        idempotency_key="idem-indexer",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="raw-indexer",
        batch_id=batch.id,
        data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://bucket/raw/course.pdf",
        checksum="raw-cs-indexer",
        mime_type="application/pdf",
        status=RawObjectStatus.RAW_PERSISTED,
        metadata_summary={},
    )
    asset = models.Asset(
        id="asset-indexer",
        data_source_id=ds.id,
        source_object_key="course.pdf",
        title="课程教材",
        asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.AVAILABLE,
    )
    version = models.AssetVersion(
        id="ver-indexer",
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum=raw.checksum,
        version_status=AssetVersionStatus.AVAILABLE,
        metadata_summary={},
    )
    ref = models.NormalizedAssetRef(
        id="ref-indexer",
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="s3://bucket/normalized/ref-indexer.json",
        schema_version="normalized-document-v1",
        checksum="ref-cs-indexer",
        status=NormalizedAssetRefStatus.GENERATED,
        block_count=chunk_count,
        record_count=0,
        source_type="file_upload",
        content_type="document",
        title="课程教材",
        language="zh-CN",
        governance={"classification": "course_textbook", "level": "L2"},
        quality={"quality_level": "pass"},
        lineage={"raw_object_id": raw.id},
        metadata_summary={"domain_profile": "course_textbook"},
    )
    chunks = []
    for index in range(chunk_count):
        chunks.append(
            models.KnowledgeChunk(
                id=f"chunk-indexer-{index}",
                normalized_ref_id=ref.id,
                knowledge_type_code="course_textbook",
                chunk_type=ChunkType.SEMANTIC_BLOCK,
                chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK,
                source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
                chunk_index=index,
                content=f"课程任务内容 {index}",
                chunk_metadata={"domain_model": "task_outline.v1"},
                embedding_status=EmbeddingStatus.PENDING,
                source_block_ids=[f"b{index}"],
                locator={"page_start": index + 1, "page_end": index + 1},
            )
        )
    session.add_all([ds, batch, raw, asset, version, ref, *chunks])
    session.commit()
    return ref, chunks


def test_index_chunks_pgvector_creates_collection_and_embeddings(session):
    ref, chunks = _seed_ref_and_chunks(session, chunk_count=2)

    result = index_chunks_pgvector(
        session,
        ref,
        chunks,
        settings=_settings(),
        embedding_client=FakeEmbeddingClient(dimension=8),
        trace_id="trace-indexer",
    )
    session.commit()

    assert result.embedded_chunk_count == 2
    assert result.collection_count == 1
    assert result.collection_keys == ["course_textbook.document.bge_m3_latest.v1"]
    assert all(chunk.embedding_status == EmbeddingStatus.EMBEDDED for chunk in chunks)
    assert session.scalar(select(func.count()).select_from(models.VectorCollection)) == 1
    assert session.scalar(select(func.count()).select_from(models.KnowledgeEmbeddingPgvector)) == 2

    row = session.scalar(
        select(models.KnowledgeEmbeddingPgvector).where(
            models.KnowledgeEmbeddingPgvector.chunk_id == chunks[0].id
        )
    )
    assert row is not None
    assert row.collection_key == "course_textbook.document.bge_m3_latest.v1"
    assert row.embedding_dimension == 8
    assert row.vector_metadata["asset"]["asset_id"] == "asset-indexer"


def test_index_chunks_pgvector_is_idempotent_on_retry(session):
    ref, chunks = _seed_ref_and_chunks(session, chunk_count=1)
    settings = _settings()

    index_chunks_pgvector(
        session,
        ref,
        chunks,
        settings=settings,
        embedding_client=FakeEmbeddingClient(dimension=8),
    )
    first_row = session.scalar(select(models.KnowledgeEmbeddingPgvector))
    first_id = first_row.id
    first_content_hash = first_row.content_hash

    chunks[0].content = "课程任务内容 retry"
    index_chunks_pgvector(
        session,
        ref,
        chunks,
        settings=settings,
        embedding_client=FakeEmbeddingClient(dimension=8),
    )
    session.commit()

    assert session.scalar(select(func.count()).select_from(models.VectorCollection)) == 1
    assert session.scalar(select(func.count()).select_from(models.KnowledgeEmbeddingPgvector)) == 1
    stored = session.scalar(select(models.KnowledgeEmbeddingPgvector))
    assert stored.id == first_id
    assert stored.content_hash != first_content_hash


class _FailingEmbeddingClient:
    def embed_texts(self, texts, *, model_alias=None, expected_dimension=None):
        raise EmbeddingClientError("simulated failure")


class _TransactionCheckingEmbeddingClient(FakeEmbeddingClient):
    def __init__(self, session, *, dimension: int):
        super().__init__(dimension=dimension)
        self._session = session

    def embed_texts(self, *args, **kwargs):
        assert not self._session.in_transaction()
        return super().embed_texts(*args, **kwargs)


class _RecordingEmbeddingClient(FakeEmbeddingClient):
    def __init__(self, *, dimension: int):
        super().__init__(dimension=dimension)
        self.calls: list[dict[str, object]] = []

    def embed_texts(self, texts, *, model_alias=None, expected_dimension=None):
        self.calls.append({
            "texts": list(texts),
            "model_alias": model_alias,
            "expected_dimension": expected_dimension,
        })
        return super().embed_texts(
            texts,
            model_alias=model_alias,
            expected_dimension=expected_dimension,
        )


def test_index_chunks_pgvector_passes_configured_embedding_dimension(session):
    ref, chunks = _seed_ref_and_chunks(session, chunk_count=2)
    settings = _settings()
    client = _RecordingEmbeddingClient(dimension=settings.default_embedding_dimension)

    index_chunks_pgvector(
        session,
        ref,
        chunks,
        settings=settings,
        embedding_client=client,
    )

    assert client.calls
    assert {call["expected_dimension"] for call in client.calls} == {
        settings.default_embedding_dimension,
    }


def test_index_embedding_call_runs_outside_database_transaction(session):
    ref, chunks = _seed_ref_and_chunks(session, chunk_count=3)

    result = index_chunks_pgvector(
        session,
        ref,
        chunks,
        settings=_settings(),
        embedding_client=_TransactionCheckingEmbeddingClient(session, dimension=8),
    )

    assert result.embedded_chunk_count == 3


def test_index_chunks_pgvector_marks_chunks_failed_on_embedding_failure(session):
    ref, chunks = _seed_ref_and_chunks(session, chunk_count=2)

    with pytest.raises(EmbeddingClientError):
        index_chunks_pgvector(
            session,
            ref,
            chunks,
            settings=_settings(),
            embedding_client=_FailingEmbeddingClient(),
        )

    assert all(chunk.embedding_status == EmbeddingStatus.FAILED for chunk in chunks)
    assert session.scalar(select(func.count()).select_from(models.KnowledgeEmbeddingPgvector)) == 0
