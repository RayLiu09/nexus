from __future__ import annotations

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
from nexus_app.index.embedding_client import EmbeddingResult
from nexus_app.index.pgvector_search import PgvectorSearchAdapter


class _StaticEmbeddingClient:
    def __init__(self, vector: list[float]) -> None:
        self.vector = vector

    def embed_texts(self, texts, *, model_alias=None, expected_dimension=None):
        return EmbeddingResult(
            vectors=[self.vector for _ in texts],
            model_alias=model_alias or "bge-m3:latest",
            dimension=expected_dimension or len(self.vector),
            request_id="static",
            latency_ms=0.0,
            input_hashes=["hash" for _ in texts],
        )


def _settings() -> Settings:
    return Settings(
        DEFAULT_EMBEDDING_MODEL="bge-m3:latest",
        DEFAULT_EMBEDDING_DIMENSION=3,
    )


def _seed_search_rows(session) -> None:
    ds = models.DataSource(
        id="ds-search",
        code="ds-search",
        name="search source",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="batch-search",
        data_source_id=ds.id,
        idempotency_key="idem-search",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="raw-search",
        batch_id=batch.id,
        data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://bucket/raw/search.pdf",
        checksum="raw-cs-search",
        mime_type="application/pdf",
        status=RawObjectStatus.RAW_PERSISTED,
        metadata_summary={},
    )
    asset = models.Asset(
        id="asset-search",
        data_source_id=ds.id,
        source_object_key="search.pdf",
        title="Search Asset",
        asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.AVAILABLE,
    )
    version = models.AssetVersion(
        id="ver-search",
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum=raw.checksum,
        version_status=AssetVersionStatus.AVAILABLE,
        metadata_summary={},
    )
    ref = models.NormalizedAssetRef(
        id="ref-search",
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="s3://bucket/normalized/ref-search.json",
        schema_version="normalized-document-v1",
        checksum="ref-cs-search",
        status=NormalizedAssetRefStatus.GENERATED,
        source_type="file_upload",
        content_type="document",
        title="Search Ref",
        language="zh-CN",
        governance={"classification": "course_textbook", "level": "L2"},
        quality={"quality_level": "pass"},
        lineage={"raw_object_id": raw.id},
        metadata_summary={"domain_profile": "course_textbook"},
    )
    collection = models.VectorCollection(
        id="vc-search",
        collection_key="course_textbook.document.bge_m3_latest.v1",
        asset_domain_type="course_textbook",
        normalized_type="document",
        embedding_provider="litellm",
        embedding_model="bge-m3:latest",
        embedding_dimension=3,
        distance_metric="cosine",
        metadata_schema_version="v1",
        collection_metadata={},
    )
    chunk_1 = models.KnowledgeChunk(
        id="chunk-search-1",
        normalized_ref_id=ref.id,
        knowledge_type_code="course_textbook",
        chunk_type=ChunkType.SEMANTIC_BLOCK,
        chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK,
        source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
        chunk_index=0,
        content="完全匹配的课程内容",
        chunk_metadata={},
        embedding_status=EmbeddingStatus.EMBEDDED,
    )
    chunk_2 = models.KnowledgeChunk(
        id="chunk-search-2",
        normalized_ref_id=ref.id,
        knowledge_type_code="industry_kb",
        chunk_type=ChunkType.SEMANTIC_BLOCK,
        chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK,
        source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
        chunk_index=1,
        content="不相关的行业内容",
        chunk_metadata={},
        embedding_status=EmbeddingStatus.EMBEDDED,
    )
    row_1 = models.KnowledgeEmbeddingPgvector(
        id="emb-search-1",
        collection_id=collection.id,
        collection_key=collection.collection_key,
        chunk_id=chunk_1.id,
        normalized_ref_id=ref.id,
        asset_id=asset.id,
        asset_version_id=version.id,
        asset_domain_type="course_textbook",
        knowledge_type_code="course_textbook",
        normalized_type="document",
        content_type="document",
        source_type="file_upload",
        language="zh-CN",
        chunk_type="semantic_block",
        chunking_strategy="semantic_repack",
        embedding_provider="litellm",
        embedding_model="bge-m3:latest",
        embedding_dimension=3,
        distance_metric="cosine",
        metadata_schema_version="v1",
        embedding=[1.0, 0.0, 0.0],
        embedding_hash="h1",
        content_hash="c1",
        vector_metadata={"asset": {"asset_id": asset.id}},
    )
    row_2 = models.KnowledgeEmbeddingPgvector(
        id="emb-search-2",
        collection_id=collection.id,
        collection_key=collection.collection_key,
        chunk_id=chunk_2.id,
        normalized_ref_id=ref.id,
        asset_id=asset.id,
        asset_version_id=version.id,
        asset_domain_type="industry_policy",
        knowledge_type_code="industry_kb",
        normalized_type="document",
        content_type="document",
        source_type="file_upload",
        language="zh-CN",
        chunk_type="semantic_block",
        chunking_strategy="semantic_repack",
        embedding_provider="litellm",
        embedding_model="bge-m3:latest",
        embedding_dimension=3,
        distance_metric="cosine",
        metadata_schema_version="v1",
        embedding=[0.0, 1.0, 0.0],
        embedding_hash="h2",
        content_hash="c2",
        vector_metadata={"asset": {"asset_id": asset.id}},
    )
    session.add_all([ds, batch, raw, asset, version, ref, collection, chunk_1, chunk_2, row_1, row_2])
    session.commit()


def test_pgvector_search_adapter_scores_and_filters_by_knowledge_type(session):
    _seed_search_rows(session)
    adapter = PgvectorSearchAdapter(
        settings=_settings(),
        embedding_client=_StaticEmbeddingClient([1.0, 0.0, 0.0]),
    )

    hits = adapter.search(
        session,
        query="课程",
        knowledge_type_code="course_textbook",
        top_k=5,
        similarity_threshold=0.7,
    )

    assert len(hits) == 1
    assert hits[0]["nexus_chunk_id"] == "chunk-search-1"
    assert hits[0]["normalized_ref_id"] == "ref-search"
    assert hits[0]["score"] == 1.0
    assert hits[0]["content"] == "完全匹配的课程内容"


def test_pgvector_search_adapter_returns_empty_below_threshold(session):
    _seed_search_rows(session)
    adapter = PgvectorSearchAdapter(
        settings=_settings(),
        embedding_client=_StaticEmbeddingClient([0.0, 0.0, 1.0]),
    )

    hits = adapter.search(
        session,
        query="无匹配",
        knowledge_type_code="course_textbook",
        top_k=5,
        similarity_threshold=0.1,
    )

    assert hits == []
