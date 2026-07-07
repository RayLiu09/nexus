"""Tests for search/qa endpoints: permission hook + audit events + source citation."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_app import models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    AuditEventType,
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


def _seed_fake_chain(session, n: int = 3) -> None:
    """Seed DataSource / IngestBatch / RawObject / Asset / AssetVersion rows
    matching FakeRAGFlowAdapter ids (fake_ds_{i}, fake_raw_{i}, fake_asset_{i},
    fake_version_{i}) so fake hits survive _filter_hits_to_available and so
    enrichment via raw.data_source_id can resolve.

    The fake adapter populates `nexus_chunk_id` directly on hits, which causes
    _enrich_with_nexus_refs to skip DB lookup; but _filter_hits_to_available
    still requires the AssetVersion row to exist and be AVAILABLE.
    """
    for i in range(1, n + 1):
        ds = models.DataSource(
            id=f"fake_ds_{i}",
            code=f"fake_ds_code_{i}",
            name=f"Fake Source {i}",
            source_type=DataSourceType.FILE_UPLOAD,
        )
        batch = models.IngestBatch(
            id=f"fake_batch_{i}",
            data_source_id=f"fake_ds_{i}",
            idempotency_key=f"idem_{i}",
            source_type=DataSourceType.FILE_UPLOAD,
            status=IngestBatchStatus.COMPLETED,
        )
        raw = models.RawObject(
            id=f"fake_raw_{i}",
            batch_id=f"fake_batch_{i}",
            data_source_id=f"fake_ds_{i}",
            source_type=DataSourceType.FILE_UPLOAD,
            object_uri=f"s3://nexus-raw/fake/{i}/source.pdf",
            checksum=f"sha256:fake_checksum_{i}",
            status=RawObjectStatus.RAW_PERSISTED,
        )
        asset = models.Asset(
            id=f"fake_asset_{i}",
            data_source_id=f"fake_ds_{i}",
            source_object_key=f"fake/key/{i}",
            title=f"Fake Asset {i}",
            asset_kind=AssetKind.DOCUMENT,
            status=AssetVersionStatus.AVAILABLE,
        )
        version = models.AssetVersion(
            id=f"fake_version_{i}",
            asset_id=f"fake_asset_{i}",
            raw_object_id=f"fake_raw_{i}",
            version_no=1,
            source_checksum=f"sha256:fake_checksum_{i}",
            version_status=AssetVersionStatus.AVAILABLE,
        )
        session.add_all([ds, batch, raw, asset, version])
    session.commit()


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


def _search_settings():
    from nexus_app.config import Settings

    return Settings(
        DEFAULT_EMBEDDING_MODEL="bge-m3:latest",
        DEFAULT_EMBEDDING_DIMENSION=3,
    )


def _seed_pgvector_search_chain(session, n: int = 3) -> None:
    ds = models.DataSource(
        id="search_ds",
        code="search_ds",
        name="Search Source",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="search_batch",
        data_source_id=ds.id,
        idempotency_key="search_idem",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="search_raw",
        batch_id=batch.id,
        data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://nexus-raw/search/source.pdf",
        checksum="sha256:search",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id="search_asset",
        data_source_id=ds.id,
        source_object_key="search/key",
        title="Search Asset",
        asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.AVAILABLE,
    )
    version = models.AssetVersion(
        id="search_version",
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum="sha256:search",
        version_status=AssetVersionStatus.AVAILABLE,
    )
    ref = models.NormalizedAssetRef(
        id="search_ref",
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="s3://bucket/normalized/search_ref.json",
        schema_version="normalized-document-v1",
        checksum="search-ref",
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
        id="search_collection",
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
    session.add_all([ds, batch, raw, asset, version, ref, collection])
    for index in range(1, n + 1):
        chunk = models.KnowledgeChunk(
            id=f"search_chunk_{index}",
            normalized_ref_id=ref.id,
            knowledge_type_code="textbook_kb",
            chunk_type=ChunkType.SEMANTIC_BLOCK,
            chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK,
            source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
            chunk_index=index - 1,
            content=f"search content {index}",
            chunk_metadata={},
            embedding_status=EmbeddingStatus.EMBEDDED,
            source_block_ids=[f"b{index}"],
            locator={"page_start": index, "page_end": index},
        )
        row = models.KnowledgeEmbeddingPgvector(
            id=f"search_embedding_{index}",
            collection_id=collection.id,
            collection_key=collection.collection_key,
            chunk_id=chunk.id,
            normalized_ref_id=ref.id,
            asset_id=asset.id,
            asset_version_id=version.id,
            asset_domain_type="course_textbook",
            knowledge_type_code="textbook_kb",
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
            embedding_hash=f"h{index}",
            content_hash=f"c{index}",
            vector_metadata={"asset": {"asset_id": asset.id}},
        )
        session.add_all([chunk, row])
    session.commit()


@pytest.fixture(autouse=True)
def use_fake_ragflow(monkeypatch):
    """Force FakeRAGFlowAdapter for these tests so we don't hit a real RAGFlow.

    Two patches are needed: kb_registry pulls `get_ragflow_adapter` via
    `from ... import ...`, so the name inside `kb_registry`'s module
    globals is a frozen copy of the original. Patching `ra.get_ragflow_adapter`
    alone does NOT redirect `KbRegistry.__init__`'s lookup."""
    from nexus_app.index import kb_registry as kr
    from nexus_app.index import ragflow_adapter as ra
    fake = ra.FakeRAGFlowAdapter()
    monkeypatch.setattr(ra, "get_ragflow_adapter", lambda settings=None: fake)
    monkeypatch.setattr(kr, "get_ragflow_adapter", lambda settings=None: fake)
    kr._default_registry = None
    yield fake
    kr._default_registry = None


def _seed_caller(session) -> models.ApiCaller:
    caller = models.ApiCaller(
        caller_key="search-test-caller",
        name="Search Test",
        org_scope=["org-1"],
        permission_scope=[],
    )
    session.add(caller)
    session.commit()
    return caller


def _audits(session, event_type: AuditEventType) -> list[models.AuditLog]:
    return list(
        session.scalars(
            select(models.AuditLog).where(models.AuditLog.event_type == event_type)
        )
    )


def _auth_headers(caller_client_id: str) -> dict:
    # Auth middleware verifies by hashed key; for tests we mock by passing client_id
    # via the convention X-Api-Caller-Id (consult require_api_caller for actual scheme).
    return {"X-Api-Caller-Id": caller_client_id}


class TestSearchEndpoint:
    def test_search_returns_results_with_source_citation(self, app, session, monkeypatch):
        _seed_pgvector_search_chain(session, n=2)
        caller = _seed_caller(session)

        from nexus_api.auth import require_api_caller
        from nexus_api.api import open as open_api
        app.dependency_overrides[require_api_caller] = lambda: caller
        monkeypatch.setattr(
            open_api,
            "get_pgvector_search_adapter",
            lambda: PgvectorSearchAdapter(
                settings=_search_settings(),
                embedding_client=_StaticEmbeddingClient([1.0, 0.0, 0.0]),
            ),
        )

        client = TestClient(app)
        resp = client.get("/open/v1/search?q=test+query&kb=textbook_kb&top_k=2")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "results" in data
        for hit in data["results"]:
            assert "normalized_ref_id" in hit
            assert "version_id" in hit
            assert "asset_id" in hit

    def test_search_writes_audit_event(self, app, session, monkeypatch):
        _seed_pgvector_search_chain(session, n=1)
        caller = _seed_caller(session)
        from nexus_api.auth import require_api_caller
        from nexus_api.api import open as open_api
        app.dependency_overrides[require_api_caller] = lambda: caller
        monkeypatch.setattr(
            open_api,
            "get_pgvector_search_adapter",
            lambda: PgvectorSearchAdapter(
                settings=_search_settings(),
                embedding_client=_StaticEmbeddingClient([1.0, 0.0, 0.0]),
            ),
        )

        client = TestClient(app)
        client.get("/open/v1/search?q=hello&kb=textbook_kb")
        events = _audits(session, AuditEventType.SEARCH_QUERY_EXECUTED)
        assert events
        last = events[-1]
        assert last.actor_id == caller.id
        assert last.summary["kb"] == "textbook_kb"
        assert "query_hash" in last.summary
        assert isinstance(last.summary.get("hit_normalized_ref_ids"), list)

    def test_search_audit_carries_data_source_ids(self, app, session, monkeypatch):
        _seed_pgvector_search_chain(session, n=3)
        caller = _seed_caller(session)
        from nexus_api.auth import require_api_caller
        from nexus_api.api import open as open_api
        app.dependency_overrides[require_api_caller] = lambda: caller
        monkeypatch.setattr(
            open_api,
            "get_pgvector_search_adapter",
            lambda: PgvectorSearchAdapter(
                settings=_search_settings(),
                embedding_client=_StaticEmbeddingClient([1.0, 0.0, 0.0]),
            ),
        )

        client = TestClient(app)
        client.get("/open/v1/search?q=ds-check&kb=textbook_kb&top_k=3")
        events = _audits(session, AuditEventType.SEARCH_QUERY_EXECUTED)
        last = events[-1]
        ds_ids = last.summary.get("data_source_ids")
        assert isinstance(ds_ids, list)
        assert ds_ids == sorted(ds_ids)
        assert ds_ids and len(set(ds_ids)) == len(ds_ids)

    def test_search_returns_empty_when_no_pgvector_hits(self, app, session, monkeypatch):
        _seed_pgvector_search_chain(session, n=1)
        caller = _seed_caller(session)
        from nexus_api.auth import require_api_caller
        from nexus_api.api import open as open_api
        app.dependency_overrides[require_api_caller] = lambda: caller
        monkeypatch.setattr(
            open_api,
            "get_pgvector_search_adapter",
            lambda: PgvectorSearchAdapter(
                settings=_search_settings(),
                embedding_client=_StaticEmbeddingClient([0.0, 0.0, 1.0]),
            ),
        )

        client = TestClient(app)
        resp = client.get("/open/v1/search?q=empty&kb=textbook_kb&similarity_threshold=0.1")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["results"] == []
        assert data["count"] == 0


class TestQAEndpoint:
    def test_qa_returns_sources_with_citation(self, app, session):
        caller = _seed_caller(session)
        from nexus_api.auth import require_api_caller
        app.dependency_overrides[require_api_caller] = lambda: caller

        client = TestClient(app)
        resp = client.get("/open/v1/qa?q=what+is+x&kb=textbook_kb")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "answer" in data
        assert "sources" in data
        for src in data["sources"]:
            assert "normalized_ref_id" in src

    def test_qa_writes_audit_event(self, app, session):
        caller = _seed_caller(session)
        from nexus_api.auth import require_api_caller
        app.dependency_overrides[require_api_caller] = lambda: caller

        client = TestClient(app)
        client.get("/open/v1/qa?q=what+is+nexus&kb=textbook_kb")
        events = _audits(session, AuditEventType.QA_ANSWER_GENERATED)
        assert events
        last = events[-1]
        assert last.actor_id == caller.id
        assert "question_hash" in last.summary
        assert "cited_normalized_ref_ids" in last.summary

    def test_qa_audit_carries_answer_confidence(self, app, session):
        """Fake qa sources carry scores 0.8/0.7/0.6; derived confidence = max."""
        _seed_fake_chain(session, n=3)
        caller = _seed_caller(session)
        from nexus_api.auth import require_api_caller
        app.dependency_overrides[require_api_caller] = lambda: caller

        client = TestClient(app)
        resp = client.get("/open/v1/qa?q=conf-check&kb=textbook_kb&top_k=3")
        data = resp.json()["data"]
        assert data.get("answer_confidence") == pytest.approx(0.8)

        events = _audits(session, AuditEventType.QA_ANSWER_GENERATED)
        last = events[-1]
        assert last.summary.get("answer_confidence") == pytest.approx(0.8)
        ds_ids = last.summary.get("data_source_ids")
        assert isinstance(ds_ids, list) and ds_ids == sorted(ds_ids)

    def test_qa_no_sources_no_confidence(self, app, session, use_fake_ragflow):
        """When the adapter returns no sources, answer_confidence must be null."""
        def empty_qa(kb_id, question, top_k=5):
            return {"answer": "no sources", "sources": []}
        use_fake_ragflow.qa = empty_qa

        caller = _seed_caller(session)
        from nexus_api.auth import require_api_caller
        app.dependency_overrides[require_api_caller] = lambda: caller

        client = TestClient(app)
        resp = client.get("/open/v1/qa?q=empty&kb=textbook_kb")
        data = resp.json()["data"]
        assert data.get("answer_confidence") is None

        events = _audits(session, AuditEventType.QA_ANSWER_GENERATED)
        last = events[-1]
        assert last.summary.get("answer_confidence") is None
        assert last.summary.get("data_source_ids") == []


class TestPermissionHookNoop:
    def test_filter_passes_hits_through_unchanged(self):
        from nexus_api.permissions import apply_permission_filter
        caller = type("C", (), {"id": "c1", "org_scope": ["org-1"]})()
        hits = [{"chunk_id": "x", "normalized_ref_id": "r1"}, {"chunk_id": "y"}]
        out = apply_permission_filter(caller, hits)
        assert len(out) == 2
        assert out is hits  # identity in P0 noop
