from __future__ import annotations

import pytest
from sqlalchemy import event, func, select

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
from nexus_app.index.query_embedding_cache import QueryEmbeddingCache
from nexus_app.index.projection_maintenance import compact_batch, cleanup_retired_batch
from nexus_app.index.collection_resolver import build_vector_metadata, resolve_collection
from nexus_app.index.vector_metadata import STORAGE_KEY, hydrate_metadata
from nexus_app.enums import IndexManifestStatus


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


def test_pgvector_search_reuses_embedding_for_repeated_query(session):
    _seed_search_rows(session)

    class CountingEmbeddingClient(_StaticEmbeddingClient):
        calls = 0

        def embed_texts(self, texts, *, model_alias=None, expected_dimension=None):
            self.calls += 1
            return super().embed_texts(
                texts, model_alias=model_alias, expected_dimension=expected_dimension,
            )

    embedding_client = CountingEmbeddingClient([1.0, 0.0, 0.0])
    adapter = PgvectorSearchAdapter(
        settings=_settings(),
        embedding_client=embedding_client,
        embedding_cache=QueryEmbeddingCache(ttl_seconds=60, max_entries=4),
    )

    first = adapter.search(
        session, query="重复查询", knowledge_type_code="course_textbook",
        top_k=5, similarity_threshold=0.7,
    )
    second = adapter.search(
        session, query="重复查询", knowledge_type_code="course_textbook",
        top_k=5, similarity_threshold=0.7,
    )

    assert first == second
    assert embedding_client.calls == 1


@pytest.mark.parametrize("field,value", [
    ("status", "disabled"), ("embedding_model", "another-model"),
    ("embedding_dimension", 1024), ("distance_metric", "l2"),
    ("normalized_type", "record"), ("asset_domain_type", "structured_record_table"),
])
def test_collection_admission_applies_to_broad_search_before_embedding(session, field, value):
    _seed_search_rows(session)
    collection = session.get(models.VectorCollection, "vc-search")
    setattr(collection, field, value)
    session.commit()

    class NeverEmbed:
        def embed_texts(self, *args, **kwargs):
            raise AssertionError("ineligible collections must not call embedding")

    adapter = PgvectorSearchAdapter(settings=_settings(), embedding_client=NeverEmbed())
    assert adapter.search(session, query="query", knowledge_type_code=None) == []


def test_collection_routing_keeps_ref_chunk_intersection(session):
    _seed_search_rows(session)
    adapter = PgvectorSearchAdapter(settings=_settings(), embedding_client=_StaticEmbeddingClient([1, 0, 0]))
    assert adapter.search(session, query="query", knowledge_type_code="course_textbook",
                          normalized_ref_ids=["another-ref"], similarity_threshold=0) == []
    assert adapter.search(session, query="query", knowledge_type_code="course_textbook",
                          chunk_ids=["chunk-search-2"], similarity_threshold=0) == []
    assert adapter.search(session, query="query", knowledge_type_code="structured_record_table",
                          similarity_threshold=0) == []


def test_reclassified_refs_are_retrievable_from_legacy_collection_without_widening_scope(session):
    _seed_search_rows(session)
    ref = session.get(models.NormalizedAssetRef, "ref-search")
    ref.governance = {"classification": "industry_regulation_standard", "level": "L2"}
    collection = session.get(models.VectorCollection, "vc-search")
    collection.asset_domain_type = "industry_research_kb"
    for row in session.scalars(select(models.KnowledgeEmbeddingPgvector)):
        row.knowledge_type_code = "industry_research_kb"
        row.asset_domain_type = "industry_research_kb"
    session.commit()
    adapter = PgvectorSearchAdapter(settings=_settings(), embedding_client=_StaticEmbeddingClient([1, 0, 0]))
    hits = adapter.search(session, query="规范", knowledge_type_code="industry_regulation_standard",
                          similarity_threshold=0.7)
    assert [hit["normalized_ref_id"] for hit in hits] == [ref.id]
    assert adapter.search(session, query="规范", knowledge_type_code="industry_policy", similarity_threshold=0) == []
    assert adapter.search(session, query="规范", knowledge_type_code="industry_regulation_standard",
                          normalized_ref_ids=["different-ref"], similarity_threshold=0) == []
    assert adapter.search(session, query="规范", knowledge_type_code="industry_research_kb", similarity_threshold=0.7)


def _legacy_metadata(session):
    ref = session.get(models.NormalizedAssetRef, "ref-search")
    ref.lineage = {"raw_object_id": "raw-search", "processing": ["retained source " * 1000]}
    chunk = session.get(models.KnowledgeChunk, "chunk-search-1")
    resolution = resolve_collection(ref, chunk, embedding_model_alias="bge-m3:latest", embedding_dimension=3)
    metadata = build_vector_metadata(ref, chunk, resolution,
                                     asset_id="asset-search", asset_version_id="ver-search")
    metadata["custom_legacy_key"] = {"keep": True}
    row = session.get(models.KnowledgeEmbeddingPgvector, "emb-search-1")
    row.vector_metadata = metadata
    session.commit()
    return metadata


def test_metadata_backfill_preserves_search_response_sources_and_audit(session):
    _seed_search_rows(session)
    legacy = _legacy_metadata(session)
    adapter = PgvectorSearchAdapter(settings=_settings(), embedding_client=_StaticEmbeddingClient([1, 0, 0]))
    before = adapter.search(session, query="课程", knowledge_type_code="course_textbook")
    dry_run = compact_batch(session)
    assert dry_run["changed"] == 1
    assert STORAGE_KEY not in session.get(models.KnowledgeEmbeddingPgvector, "emb-search-1").vector_metadata
    result = compact_batch(session, apply=True, trace_id="test-compact")
    session.commit()
    assert result["json_bytes_after"] < result["json_bytes_before"] / 5
    assert session.get(models.NormalizedAssetRef, "ref-search").lineage == legacy["normalized_ref"]["lineage"]

    queries = []
    def record_query(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)
    event.listen(session.bind, "before_cursor_execute", record_query)
    try:
        after = adapter.search(session, query="课程", knowledge_type_code="course_textbook")
    finally:
        event.remove(session.bind, "before_cursor_execute", record_query)
    assert before == after
    assert after[0]["metadata"] == legacy
    assert len([q for q in queries if q.startswith("SELECT normalized_asset_ref.id,")]) == 1
    assert compact_batch(session, apply=True)["changed"] == 0
    assert session.scalar(select(func.count()).select_from(models.AuditLog)) == 1


def test_metadata_backfill_reconciles_divergent_legacy_fields(session):
    _seed_search_rows(session)
    legacy = _legacy_metadata(session)
    ref = session.get(models.NormalizedAssetRef, "ref-search")
    ref.quality = {"quality_level": "newer-canonical-value"}
    session.commit()
    result = compact_batch(session, apply=True)
    session.commit()
    assert result["mismatched_fields"] == 1
    stored = session.get(models.KnowledgeEmbeddingPgvector, "emb-search-1").vector_metadata
    assert "quality" not in stored["normalized_ref"]
    assert "quality" in stored[STORAGE_KEY]
    assert hydrate_metadata(stored, ref)["normalized_ref"]["quality"] == ref.quality


@pytest.mark.parametrize("compacted", [False, True])
def test_search_can_defer_lineage_without_changing_governance_or_ranking(session, compacted):
    from copy import deepcopy

    _seed_search_rows(session)
    legacy = _legacy_metadata(session)
    before = deepcopy(legacy)
    if compacted:
        compact_batch(session, apply=True)
        session.commit()
    session.expire_all()
    adapter = PgvectorSearchAdapter(
        settings=_settings(), embedding_client=_StaticEmbeddingClient([1, 0, 0]),
    )
    queries = []

    def record_query(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(session.bind, "before_cursor_execute", record_query)
    try:
        light = adapter.search(
            session, query="课程", knowledge_type_code="course_textbook", include_lineage=False,
        )
    finally:
        event.remove(session.bind, "before_cursor_execute", record_query)
    assert light
    assert "lineage" not in light[0]["metadata"]["normalized_ref"]
    assert not any("normalized_asset_ref.lineage" in q for q in queries)
    full = adapter.search(session, query="课程", knowledge_type_code="course_textbook")
    assert [(h["nexus_chunk_id"], h["score"], h["content"]) for h in light] == [
        (h["nexus_chunk_id"], h["score"], h["content"]) for h in full
    ]
    assert light[0]["metadata"]["normalized_ref"]["governance"] == full[0]["metadata"]["normalized_ref"]["governance"]
    assert light[0]["metadata"]["normalized_ref"]["quality"] == full[0]["metadata"]["normalized_ref"]["quality"]
    assert full[0]["metadata"]["normalized_ref"]["lineage"] == before["normalized_ref"]["lineage"]
    assert legacy == before


def test_retired_cleanup_preserves_assets_domain_sources_and_active_vectors(session):
    _seed_search_rows(session)
    retired = models.VectorCollection(
        id="retired-collection", collection_key="structured_record_table.record.model.v1",
        asset_domain_type="structured_record_table", normalized_type="record",
        embedding_model="bge-m3:latest", embedding_dimension=3, distance_metric="cosine",
    )
    session.add(retired)
    row = session.get(models.KnowledgeEmbeddingPgvector, "emb-search-2")
    row.collection_id = retired.id
    row.knowledge_type_code = "structured_record_table"
    row.normalized_type = "record"
    session.add_all([
        models.IndexManifest(normalized_ref_id="ref-search", knowledge_type_code="structured_record_table",
                             index_status=IndexManifestStatus.INDEXED, chunk_count=1),
        models.IndexManifest(normalized_ref_id="ref-search", knowledge_type_code="course_textbook",
                             index_status=IndexManifestStatus.INDEXED, chunk_count=1),
    ])
    session.commit()
    assert cleanup_retired_batch(session)["vectors"] == 1
    assert session.get(models.KnowledgeEmbeddingPgvector, "emb-search-2") is not None
    result = cleanup_retired_batch(session, apply=True, trace_id="test-retirement")
    session.commit()
    assert result["vectors"] == 1 and result["collections"] == 1
    assert session.get(models.VectorCollection, retired.id) is None
    assert session.scalar(select(func.count()).select_from(models.KnowledgeChunk)) == 2
    assert session.get(models.NormalizedAssetRef, "ref-search") is not None
    assert session.get(models.Asset, "asset-search") is not None
    manifests = {m.knowledge_type_code: m for m in session.scalars(select(models.IndexManifest))}
    assert manifests["structured_record_table"].index_status == IndexManifestStatus.STALE
    assert manifests["course_textbook"].index_status == IndexManifestStatus.INDEXED
    again = cleanup_retired_batch(session, apply=True)
    assert again["vectors"] == 0 and again["collections"] == 0
    assert session.scalar(select(func.count()).select_from(models.AuditLog)) == 1
