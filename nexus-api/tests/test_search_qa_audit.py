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


class _FakeQAService:
    def __init__(self, sources: list[dict], answer: str = "fake answer") -> None:
        self.sources = sources
        self.answer_text = answer
        self.generate_calls: list[dict] = []

    def retrieve_sources(self, session, *, question, knowledge_type_code=None, top_k=5):
        return self.sources[:top_k]

    def generate_answer(self, *, question, sources):
        self.generate_calls.append({"question": question, "sources": list(sources)})
        return {"answer": self.answer_text, "sources": sources, "model_alias": "qa-model"}


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
    @pytest.mark.parametrize("response_view", ["full", "answer"])
    @pytest.mark.parametrize("failure", ["rate_limit", "timeout"])
    def test_embedding_failure_is_503_and_connection_recovers(
        self, app, session, monkeypatch, caplog, response_view, failure,
    ):
        import httpx
        from nexus_api.api import open as open_api
        from nexus_api.auth import require_api_caller
        from nexus_app.index.embedding_client import LiteLLMEmbeddingClient

        _seed_pgvector_search_chain(session, n=1)
        caller = _seed_caller(session)
        app.dependency_overrides[require_api_caller] = lambda: caller
        calls = []

        def post(url, **kwargs):
            calls.append(url)
            request = httpx.Request("POST", url)
            if len(calls) <= 2:
                if failure == "timeout":
                    raise httpx.ReadTimeout("private-upstream-diagnostic", request=request)
                return httpx.Response(429, request=request, json={
                    "error": {"message": "private-upstream-diagnostic"},
                })
            return httpx.Response(200, request=request, json={
                "data": [{"embedding": [1.0, 0.0, 0.0]}],
            })

        monkeypatch.setattr(httpx, "post", post)
        adapter = PgvectorSearchAdapter(
            settings=_search_settings(), embedding_client=LiteLLMEmbeddingClient(
                endpoint="https://embedding.invalid", api_key="test-credential",
                default_model_alias="bge-m3:latest",
            ),
        )
        monkeypatch.setattr(open_api, "get_pgvector_search_adapter", lambda: adapter)
        with TestClient(app) as client:
            params = {"q": "private-question", "kb": "textbook_kb", "response_view": response_view}
            for index in range(2):
                trace = f"embedding-failure-{index}"
                result = client.get("/open/v1/search", params=params, headers={"X-Trace-ID": trace})
                assert result.status_code == 503
                assert result.json()["error"]["message"] == "search_embedding_unavailable"
                assert result.json()["meta"]["trace_id"] == trace
                assert result.headers["X-Trace-ID"] == trace
                assert "private-upstream-diagnostic" not in result.text
                assert not _audits(session, AuditEventType.SEARCH_QUERY_EXECUTED)
            recovered = client.get("/open/v1/search", params=params)
            assert recovered.status_code == 200
            assert recovered.json()["data"]["count"] == 1
        assert len(calls) == 3  # Each request calls upstream once, without retry.
        assert len(_audits(session, AuditEventType.SEARCH_QUERY_EXECUTED)) == 1
        assert "public_search_embedding_unavailable" in caplog.text
        server_logs = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("nexus_"))
        assert "private-question" not in server_logs
        assert "private-upstream-diagnostic" not in server_logs
        assert "test-credential" not in server_logs

    def test_answer_view_defers_evidence_keeps_permissions_audit_and_content(
        self, app, session, monkeypatch,
    ):
        from copy import deepcopy
        from sqlalchemy import event

        from nexus_app.index.collection_resolver import build_vector_metadata, resolve_collection
        from nexus_app.index.projection_maintenance import compact_batch
        from nexus_api.api import open as open_api
        from nexus_api.auth import require_api_caller

        _seed_pgvector_search_chain(session, n=3)
        caller = _seed_caller(session)
        ref = session.get(models.NormalizedAssetRef, "search_ref")
        lineage = {"raw_object_id": "search_raw", "image_uris": [
            f"s3://bucket/parsed/version/artifact/images/{i}-{'x' * 150}.png" for i in range(423)
        ]}
        ref.lineage = deepcopy(lineage)
        for index in range(1, 4):
            chunk = session.get(models.KnowledgeChunk, f"search_chunk_{index}")
            chunk.content = f"课程{index}的操作流程与注意事项。" * 300
            resolution = resolve_collection(
                ref, chunk, embedding_model_alias="bge-m3:latest", embedding_dimension=3,
            )
            row = session.get(models.KnowledgeEmbeddingPgvector, f"search_embedding_{index}")
            row.vector_metadata = build_vector_metadata(
                ref, chunk, resolution, asset_id="search_asset", asset_version_id="search_version",
            )
        session.commit()
        compact_batch(session, apply=True)
        session.commit()
        session.expire_all()
        app.dependency_overrides[require_api_caller] = lambda: caller
        adapter = PgvectorSearchAdapter(
            settings=_search_settings(), embedding_client=_StaticEmbeddingClient([1, 0, 0]),
        )
        monkeypatch.setattr(open_api, "get_pgvector_search_adapter", lambda: adapter)
        permission_inputs = []

        def permission_filter(actual_caller, hits):
            assert actual_caller.id == caller.id
            permission_inputs.append(deepcopy(hits))
            return [h for h in hits if h["nexus_chunk_id"] != "search_chunk_2"]

        monkeypatch.setattr(open_api, "apply_permission_filter", permission_filter)
        queries = []

        def record_query(conn, cursor, statement, parameters, context, executemany):
            queries.append(statement)

        with TestClient(app) as client:
            params = {"q": "课程", "kb": "textbook_kb", "top_k": 3}
            full = client.get("/open/v1/search", params=params).json()["data"]
            explicit = client.get("/open/v1/search", params={**params, "response_view": "full"}).json()["data"]
            assert explicit == full
            assert "response_view" not in full and "source_kind" not in full
            session.expire_all()
            event.listen(session.bind, "before_cursor_execute", record_query)
            try:
                answer_response = client.get("/open/v1/search", params={
                    **params, "response_view": "answer", "answer_max_chars": 100,
                }, headers={"X-Trace-ID": "answer-view-trace"})
            finally:
                event.remove(session.bind, "before_cursor_execute", record_query)
            assert answer_response.status_code == 200
            answer = answer_response.json()["data"]
            assert answer["response_view"] == "answer" and answer["source_kind"] == "platform"
            assert answer["count"] == full["count"] == 2
            assert not any("normalized_asset_ref.lineage" in q for q in queries)
            assert len(answer_response.content) < len(str(full).encode()) / 30
            for before, after in zip(full["results"], answer["results"]):
                for key in ("nexus_chunk_id", "normalized_ref_id", "score", "knowledge_type_code"):
                    assert after[key] == before[key]
                assert after["content"] == before["content"][:100]
                assert after["content_chars"] == len(before["content"])
                assert after["content_truncated"] is True
                assert after["title"] == "Search Ref"
                assert not ({"metadata", "locator", "source_block_ids", "raw_object_uri", "knowledge_outline"} & after.keys())
            # No canonical lineage was removed; citation resolution is a later call.
            normalized = client.get("/open/v1/normalized-refs/search_ref").json()["data"]
            assert normalized["lineage"] == lineage
            citation = client.post("/open/v1/evidence-resolutions", json={
                "references": [{"kind": "chunk", "id": answer["results"][0]["nexus_chunk_id"]}],
                "max_chars": 100,
            })
            assert citation.status_code == 200
            evidence = citation.json()["data"][0]
            assert evidence["normalized_ref_id"] == "search_ref"
            assert evidence["locator"] == full["results"][0]["locator"]
            assert evidence["content"] == full["results"][0]["content"][:100]
        events = _audits(session, AuditEventType.SEARCH_QUERY_EXECUTED)
        audit = next(x for x in events if x.trace_id == "answer-view-trace")
        assert audit.actor_id == caller.id
        assert audit.summary["response_view"] == "answer"
        assert audit.summary["cited_chunk_ids"] == [h["nexus_chunk_id"] for h in full["results"]]
        assert audit.summary["hit_normalized_ref_ids"] == ["search_ref", "search_ref"]
        assert audit.summary["data_source_ids"] == ["search_ds"]
        assert len(audit.summary["cited_locators"]) == 2
        assert set(audit.summary["stage_timings_ms"]) == {"scope", "retrieval", "enrichment_and_gates", "projection"}
        assert len(permission_inputs) == 3
        metadata = permission_inputs[-1][0]["metadata"]["normalized_ref"]
        assert metadata["governance"]["classification"] == "course_textbook"
        assert metadata["quality"]["quality_level"] == "pass"
        assert "lineage" not in metadata

    @pytest.mark.parametrize("query", [
        "response_view=unknown", "response_view=answer&answer_max_chars=99",
        "response_view=answer&answer_max_chars=10001",
    ])
    def test_invalid_answer_view_parameters_are_rejected(self, app, query):
        with TestClient(app) as client:
            assert client.get(f"/open/v1/search?q=test&{query}").status_code == 422

    def test_answer_view_still_requires_real_authentication(self, app_no_auth_override):
        with TestClient(app_no_auth_override) as client:
            result = client.get("/open/v1/search?q=test&response_view=answer")
        assert result.status_code == 401

    @pytest.mark.parametrize("classification_added_after_index", [False, True])
    @pytest.mark.parametrize("level", ["L2", "L3"])
    def test_compaction_preserves_full_search_payload_and_source_trace(
        self, app, session, monkeypatch, classification_added_after_index, level,
    ):
        from copy import deepcopy

        from nexus_app.index.collection_resolver import build_vector_metadata, resolve_collection
        from nexus_app.index.projection_maintenance import compact_batch
        from nexus_app.index.vector_metadata import STORAGE_KEY
        from nexus_api.api import open as open_api
        from nexus_api.auth import require_api_caller
        from nexus_api.public_query_tools import safe_data

        _seed_pgvector_search_chain(session, n=1)
        caller = _seed_caller(session)
        ref = session.get(models.NormalizedAssetRef, "search_ref")
        chunk = session.get(models.KnowledgeChunk, "search_chunk_1")
        row = session.get(models.KnowledgeEmbeddingPgvector, "search_embedding_1")
        ref.governance = {
            **ref.governance, "level": level,
            "classification_name": "课程教材", "classification_confidence": 0.96,
        }
        resolution = resolve_collection(
            ref, chunk, embedding_model_alias="bge-m3:latest", embedding_dimension=3,
        )
        original = build_vector_metadata(
            ref, chunk, resolution, asset_id="search_asset", asset_version_id="search_version",
        )
        if classification_added_after_index:
            # Reproduce the observed historical snapshot: only the canonical
            # ref has the subsequently added classification fields.
            for field in ("classification", "classification_name", "classification_confidence"):
                original["normalized_ref"]["governance"].pop(field)
            # build_vector_metadata exposes the ORM dictionaries; keep the
            # historical snapshot and canonical value independently owned.
            ref.governance = {
                "level": level, "classification": "industry_regulation_standard",
                "classification_name": "行业法规标准", "classification_confidence": 0.96,
            }
        row.vector_metadata = deepcopy(original)
        session.commit()
        app.dependency_overrides[require_api_caller] = lambda: caller
        monkeypatch.setattr(open_api, "get_pgvector_search_adapter", lambda: PgvectorSearchAdapter(
            settings=_search_settings(), embedding_client=_StaticEmbeddingClient([1.0, 0.0, 0.0]),
        ))

        with TestClient(app) as client:
            before_response = client.get("/open/v1/search?q=trace&kb=textbook_kb&top_k=1")
            assert before_response.status_code == 200
            before = before_response.json()["data"]["results"]
            assert len(before) == 1

            result = compact_batch(session, batch_size=10, apply=True, trace_id="compact-trace-test")
            session.commit()
            assert result["changed"] == 1
            stored = session.get(models.KnowledgeEmbeddingPgvector, row.id).vector_metadata
            assert "lineage" in stored[STORAGE_KEY]
            assert "governance" in stored[STORAGE_KEY]

            after_response = client.get("/open/v1/search?q=trace&kb=textbook_kb&top_k=1")
            assert after_response.status_code == 200
            after = after_response.json()["data"]["results"]

        expected = deepcopy(before)
        expected[0]["metadata"]["normalized_ref"]["governance"] = ref.governance
        for field in ("classification", "level", "tags", "org_scope"):
            if field in ref.governance:
                expected[0]["metadata"]["asset"][field] = ref.governance[field]
        assert after == expected
        assert after[0]["raw_object_id"] == "search_raw"
        assert after[0]["raw_object_uri"] == "s3://nexus-raw/search/source.pdf"
        assert after[0]["version_id"] == "search_version"
        assert after[0]["asset_id"] == "search_asset"
        assert after[0]["normalized_ref_id"] == "search_ref"
        assert after[0]["nexus_chunk_id"] == "search_chunk_1"
        assert after[0]["source_block_ids"] == ["b1"]
        assert after[0]["locator"] == {"page_start": 1, "page_end": 1}
        assert safe_data(after) == safe_data(expected)
        if level == "L3":
            assert safe_data(after)[0]["metadata"]["normalized_ref"]["restricted"] is True

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
        response = client.get("/open/v1/search?q=hello&kb=textbook_kb")
        assert response.status_code == 200
        events = _audits(session, AuditEventType.SEARCH_QUERY_EXECUTED)
        assert events
        last = events[-1]
        assert response.json()["meta"]["trace_id"]
        assert last.trace_id == response.json()["meta"]["trace_id"]
        assert last.actor_id == caller.id
        assert last.summary["kb"] == "textbook_kb"
        assert "query_hash" in last.summary
        assert isinstance(last.summary.get("hit_normalized_ref_ids"), list)
        # A7 (§10 阶段 A) — legacy /open/v1/search must carry caller_type
        # + route so v1 rows share the v2 audit shape.
        assert last.summary["caller_type"] == "api_caller"
        assert last.summary["route"] == "search"

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
    def test_qa_returns_sources_with_citation(self, app, session, monkeypatch):
        _seed_pgvector_search_chain(session, n=1)
        caller = _seed_caller(session)
        from nexus_api.auth import require_api_caller
        from nexus_api.api import open as open_api
        app.dependency_overrides[require_api_caller] = lambda: caller
        monkeypatch.setattr(
            open_api,
            "get_pgvector_qa_service",
            lambda: _FakeQAService(
                [
                    {
                        "nexus_chunk_id": "search_chunk_1",
                        "normalized_ref_id": "search_ref",
                        "score": 0.8,
                        "content": "search content 1",
                    }
                ]
            ),
        )

        client = TestClient(app)
        resp = client.get("/open/v1/qa?q=what+is+x&kb=textbook_kb")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "answer" in data
        assert "sources" in data
        for src in data["sources"]:
            assert "normalized_ref_id" in src

    def test_qa_writes_audit_event(self, app, session, monkeypatch):
        _seed_pgvector_search_chain(session, n=1)
        caller = _seed_caller(session)
        from nexus_api.auth import require_api_caller
        from nexus_api.api import open as open_api
        app.dependency_overrides[require_api_caller] = lambda: caller
        monkeypatch.setattr(
            open_api,
            "get_pgvector_qa_service",
            lambda: _FakeQAService(
                [
                    {
                        "nexus_chunk_id": "search_chunk_1",
                        "normalized_ref_id": "search_ref",
                        "score": 0.8,
                        "content": "search content 1",
                    }
                ]
            ),
        )

        client = TestClient(app)
        client.get("/open/v1/qa?q=what+is+nexus&kb=textbook_kb")
        events = _audits(session, AuditEventType.QA_ANSWER_GENERATED)
        assert events
        last = events[-1]
        assert last.actor_id == caller.id
        assert "question_hash" in last.summary
        assert "cited_normalized_ref_ids" in last.summary
        # A7 (§10 阶段 A) — legacy /open/v1/qa must carry caller_type + route.
        assert last.summary["caller_type"] == "api_caller"
        assert last.summary["route"] == "qa"

    def test_qa_audit_carries_answer_confidence(self, app, session, monkeypatch):
        _seed_pgvector_search_chain(session, n=3)
        caller = _seed_caller(session)
        from nexus_api.auth import require_api_caller
        from nexus_api.api import open as open_api
        app.dependency_overrides[require_api_caller] = lambda: caller
        monkeypatch.setattr(
            open_api,
            "get_pgvector_qa_service",
            lambda: _FakeQAService(
                [
                    {
                        "nexus_chunk_id": "search_chunk_1",
                        "normalized_ref_id": "search_ref",
                        "score": 0.8,
                        "content": "search content 1",
                    },
                    {
                        "nexus_chunk_id": "search_chunk_2",
                        "normalized_ref_id": "search_ref",
                        "score": 0.7,
                        "content": "search content 2",
                    },
                    {
                        "nexus_chunk_id": "search_chunk_3",
                        "normalized_ref_id": "search_ref",
                        "score": 0.6,
                        "content": "search content 3",
                    },
                ]
            ),
        )

        client = TestClient(app)
        resp = client.get("/open/v1/qa?q=conf-check&kb=textbook_kb&top_k=3")
        data = resp.json()["data"]
        assert data.get("answer_confidence") == pytest.approx(0.8)

        events = _audits(session, AuditEventType.QA_ANSWER_GENERATED)
        last = events[-1]
        assert last.summary.get("answer_confidence") == pytest.approx(0.8)
        ds_ids = last.summary.get("data_source_ids")
        assert isinstance(ds_ids, list) and ds_ids == sorted(ds_ids)

    def test_qa_no_sources_no_confidence(self, app, session, monkeypatch):
        caller = _seed_caller(session)
        from nexus_api.auth import require_api_caller
        from nexus_api.api import open as open_api
        app.dependency_overrides[require_api_caller] = lambda: caller
        monkeypatch.setattr(
            open_api,
            "get_pgvector_qa_service",
            lambda: _FakeQAService([], answer="no sources"),
        )

        client = TestClient(app)
        resp = client.get("/open/v1/qa?q=empty&kb=textbook_kb")
        data = resp.json()["data"]
        assert data.get("answer_confidence") is None

        events = _audits(session, AuditEventType.QA_ANSWER_GENERATED)
        last = events[-1]
        assert last.summary.get("answer_confidence") is None
        assert last.summary.get("data_source_ids") == []

    def test_qa_generates_answer_after_available_filtering(self, app, session, monkeypatch):
        _seed_pgvector_search_chain(session, n=1)
        caller = _seed_caller(session)
        qa = _FakeQAService(
            [
                {
                    "nexus_chunk_id": "search_chunk_1",
                    "normalized_ref_id": "search_ref",
                    "score": 0.8,
                    "content": "available content",
                },
                {
                    "nexus_chunk_id": "missing_chunk",
                    "normalized_ref_id": "missing_ref",
                    "version_id": "missing_version",
                    "score": 0.9,
                    "content": "filtered content",
                },
            ]
        )
        from nexus_api.auth import require_api_caller
        from nexus_api.api import open as open_api
        app.dependency_overrides[require_api_caller] = lambda: caller
        monkeypatch.setattr(open_api, "get_pgvector_qa_service", lambda: qa)

        client = TestClient(app)
        resp = client.get("/open/v1/qa?q=filter-check&kb=textbook_kb&top_k=2")

        assert resp.status_code == 200
        assert len(qa.generate_calls) == 1
        generated_sources = qa.generate_calls[0]["sources"]
        assert [source["nexus_chunk_id"] for source in generated_sources] == ["search_chunk_1"]
        assert "filtered content" not in str(generated_sources)


class TestPermissionHookNoop:
    def test_filter_passes_hits_through_unchanged(self):
        from nexus_api.permissions import apply_permission_filter
        caller = type("C", (), {"id": "c1", "org_scope": ["org-1"]})()
        hits = [{"chunk_id": "x", "normalized_ref_id": "r1"}, {"chunk_id": "y"}]
        out = apply_permission_filter(caller, hits)
        assert len(out) == 2
        assert out is hits  # identity in P0 noop
