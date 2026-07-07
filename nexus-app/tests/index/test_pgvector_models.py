from __future__ import annotations

from sqlalchemy import select

from nexus_app import models
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
from nexus_app.index.collection_resolver import build_vector_projection, resolve_collection


def _seed_chunk(session) -> tuple[models.NormalizedAssetRef, models.KnowledgeChunk]:
    ds = models.DataSource(
        id="ds-pgv",
        code="ds-pgv",
        name="pgvector source",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="batch-pgv",
        data_source_id=ds.id,
        idempotency_key="idem-pgv",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="raw-pgv",
        batch_id=batch.id,
        data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://bucket/raw/course.pdf",
        checksum="raw-cs-pgv",
        mime_type="application/pdf",
        status=RawObjectStatus.RAW_PERSISTED,
        metadata_summary={},
    )
    asset = models.Asset(
        id="asset-pgv",
        data_source_id=ds.id,
        source_object_key="course.pdf",
        title="课程教材",
        asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.PROCESSING,
    )
    version = models.AssetVersion(
        id="ver-pgv",
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum=raw.checksum,
        version_status=AssetVersionStatus.PROCESSING,
        metadata_summary={},
    )
    ref = models.NormalizedAssetRef(
        id="ref-pgv",
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="s3://bucket/normalized/ref-pgv.json",
        schema_version="normalized-document-v1",
        checksum="ref-cs-pgv",
        status=NormalizedAssetRefStatus.GENERATED,
        block_count=1,
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
    chunk = models.KnowledgeChunk(
        id="chunk-pgv",
        normalized_ref_id=ref.id,
        knowledge_type_code="course_textbook",
        chunk_type=ChunkType.SEMANTIC_BLOCK,
        chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK,
        source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
        chunk_index=0,
        content="课程任务内容",
        chunk_metadata={"domain_model": "task_outline.v1"},
        embedding_status=EmbeddingStatus.PENDING,
        source_block_ids=["b1"],
        locator={"page_start": 1, "page_end": 1},
    )
    session.add_all([ds, batch, raw, asset, version, ref, chunk])
    session.commit()
    return ref, chunk


def test_pgvector_projection_models_insert_on_sqlite(session):
    ref, chunk = _seed_chunk(session)
    resolution = resolve_collection(
        ref,
        chunk,
        embedding_model_alias="bge-m3:latest",
        embedding_dimension=1024,
    )
    collection = models.VectorCollection(
        collection_key=resolution.collection_key,
        asset_domain_type=resolution.asset_domain_type,
        normalized_type=resolution.normalized_type,
        embedding_provider=resolution.embedding_provider,
        embedding_model=resolution.embedding_model,
        embedding_dimension=resolution.embedding_dimension,
        distance_metric=resolution.distance_metric,
        metadata_schema_version=resolution.metadata_schema_version,
        collection_metadata={"purpose": "semantic_retrieval"},
    )
    session.add(collection)
    session.flush()

    projection = build_vector_projection(
        ref,
        chunk,
        resolution,
        embedding=[0.1, 0.2, 0.3],
        asset_id="asset-pgv",
        asset_version_id="ver-pgv",
    )
    row = models.KnowledgeEmbeddingPgvector(
        collection_id=collection.id,
        **projection.columns,
    )
    session.add(row)
    session.commit()

    stored = session.scalar(
        select(models.KnowledgeEmbeddingPgvector).where(
            models.KnowledgeEmbeddingPgvector.chunk_id == "chunk-pgv"
        )
    )

    assert stored is not None
    assert stored.collection_key == "course_textbook.document.bge_m3_latest.v1"
    assert stored.embedding == [0.1, 0.2, 0.3]
    assert stored.vector_metadata["asset"]["asset_id"] == "asset-pgv"
    assert stored.vector_metadata["index"]["embedding_provider"] == "litellm"
