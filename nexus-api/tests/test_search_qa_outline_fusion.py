"""Search / QA fusion with knowledge outline citations.

Verifies hits carry `knowledge_outline` breadcrumbs when the chunk is linked
to a theory_knowledge textbook outline, and that `?outline_node=<id>`
restricts search hits to that subtree.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

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
from nexus_app.index.embedding_client import EmbeddingResult
from nexus_app.index.pgvector_search import PgvectorSearchAdapter


class _StaticEmbeddingClient:
    def __init__(self, vector):
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


def _settings():
    from nexus_app.config import Settings

    return Settings(
        DEFAULT_EMBEDDING_MODEL="bge-m3:latest",
        DEFAULT_EMBEDDING_DIMENSION=3,
    )


def _seed_caller(session):
    caller = models.ApiCaller(
        caller_key="outline-fusion-caller",
        name="Outline Fusion",
        org_scope=[],
        permission_scope=[],
    )
    session.add(caller)
    session.commit()
    return caller


def _seed_textbook_with_outline(session):
    """Seed a textbook with 3 chunks linked to 3 leaf outline nodes:

        root
          ├─ 第1章 引论
          │    └─ 1.1 概念     ← chunk-1
          │    └─ 1.2 边界     ← chunk-2
          └─ 第2章 应用        ← chunk-3
    """
    ds = models.DataSource(id="ds-o", code="ds-o", name="outline",
                           source_type=DataSourceType.FILE_UPLOAD)
    batch = models.IngestBatch(
        id="b-o", data_source_id=ds.id, idempotency_key="idem-o",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="r-o", batch_id=batch.id, data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://b/raw/o.pdf", checksum="cs-o",
        mime_type="application/pdf", status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id="a-o", data_source_id=ds.id, source_object_key="o.pdf",
        title="理论教材", asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.AVAILABLE,
    )
    version = models.AssetVersion(
        id="v-o", asset_id=asset.id, raw_object_id=raw.id, version_no=1,
        source_checksum="cs-o", version_status=AssetVersionStatus.AVAILABLE,
    )
    ref = models.NormalizedAssetRef(
        id="ref-o", version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="s3://b/norm/o.json",
        schema_version="normalized-document-v1", checksum="ref-o",
        status=NormalizedAssetRefStatus.GENERATED,
        source_type="file_upload", content_type="document",
        title="理论教材", language="zh-CN",
        governance={"classification": "course_textbook"}, quality={},
        lineage={"raw_object_id": raw.id}, metadata_summary={},
    )
    collection = models.VectorCollection(
        id="col-o", collection_key="course_textbook.document.bge_m3_latest.v1",
        asset_domain_type="course_textbook", normalized_type="document",
        embedding_provider="litellm", embedding_model="bge-m3:latest",
        embedding_dimension=3, distance_metric="cosine",
        metadata_schema_version="v1", collection_metadata={},
    )
    session.add_all([ds, batch, raw, asset, version, ref, collection])

    root = models.KnowledgeOutlineNode(
        id="on-root", normalized_ref_id=ref.id, parent_id=None,
        level=0, order_index=0, title="理论教材",
        numbering=None, numbering_path=None, anchor_range=None,
        chunk_count=0, build_run_id="run-1", fallback_used=False,
    )
    chap1 = models.KnowledgeOutlineNode(
        id="on-ch1", normalized_ref_id=ref.id, parent_id=root.id,
        level=1, order_index=0, title="第1章 引论",
        numbering="1", numbering_path=[1], anchor_range=None,
        chunk_count=0, build_run_id="run-1", fallback_used=False,
    )
    sec11 = models.KnowledgeOutlineNode(
        id="on-1-1", normalized_ref_id=ref.id, parent_id=chap1.id,
        level=2, order_index=0, title="1.1 概念",
        numbering="1.1", numbering_path=[1, 1],
        anchor_range={"block_ids": ["b1"]},
        chunk_count=1, build_run_id="run-1", fallback_used=False,
    )
    sec12 = models.KnowledgeOutlineNode(
        id="on-1-2", normalized_ref_id=ref.id, parent_id=chap1.id,
        level=2, order_index=1, title="1.2 边界",
        numbering="1.2", numbering_path=[1, 2],
        anchor_range={"block_ids": ["b2"]},
        chunk_count=1, build_run_id="run-1", fallback_used=False,
    )
    chap2 = models.KnowledgeOutlineNode(
        id="on-ch2", normalized_ref_id=ref.id, parent_id=root.id,
        level=1, order_index=1, title="第2章 应用",
        numbering="2", numbering_path=[2],
        anchor_range={"block_ids": ["b3"]},
        chunk_count=1, build_run_id="run-1", fallback_used=False,
    )
    session.add_all([root, chap1, sec11, sec12, chap2])

    for idx, (chunk_id, outline_node_id) in enumerate(
        [("chk-1", sec11.id), ("chk-2", sec12.id), ("chk-3", chap2.id)],
        start=1,
    ):
        chunk = models.KnowledgeChunk(
            id=chunk_id, normalized_ref_id=ref.id,
            knowledge_type_code="textbook_kb",
            chunk_type=ChunkType.SEMANTIC_BLOCK,
            chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK,
            source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
            chunk_index=idx - 1, content=f"内容 {idx}",
            chunk_metadata={}, embedding_status=EmbeddingStatus.EMBEDDED,
            source_block_ids=[f"b{idx}"],
            locator={"page_start": idx, "page_end": idx},
            knowledge_outline_node_id=outline_node_id,
        )
        row = models.KnowledgeEmbeddingPgvector(
            id=f"emb-{idx}", collection_id=collection.id,
            collection_key=collection.collection_key, chunk_id=chunk.id,
            normalized_ref_id=ref.id, asset_id=asset.id,
            asset_version_id=version.id, asset_domain_type="course_textbook",
            knowledge_type_code="textbook_kb", normalized_type="document",
            content_type="document", source_type="file_upload",
            language="zh-CN", chunk_type="semantic_block",
            chunking_strategy="semantic_repack",
            embedding_provider="litellm", embedding_model="bge-m3:latest",
            embedding_dimension=3, distance_metric="cosine",
            metadata_schema_version="v1", embedding=[1.0, 0.0, 0.0],
            embedding_hash=f"eh-{idx}", content_hash=f"ch-{idx}",
            vector_metadata={"asset": {"asset_id": asset.id}},
        )
        session.add_all([chunk, row])
    session.commit()
    return ref, chap1


def _wire_search_adapter(app, monkeypatch, caller):
    from nexus_api.auth import require_api_caller
    from nexus_api.api import open as open_api

    app.dependency_overrides[require_api_caller] = lambda: caller
    monkeypatch.setattr(
        open_api, "get_pgvector_search_adapter",
        lambda: PgvectorSearchAdapter(
            settings=_settings(),
            embedding_client=_StaticEmbeddingClient([1.0, 0.0, 0.0]),
        ),
    )


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------


def test_search_hit_includes_outline_breadcrumb(app, session, monkeypatch):
    _seed_textbook_with_outline(session)
    caller = _seed_caller(session)
    _wire_search_adapter(app, monkeypatch, caller)

    with TestClient(app) as client:
        resp = client.get("/open/v1/search?q=概念&kb=textbook_kb&top_k=10")

    assert resp.status_code == 200
    hits = resp.json()["data"]["results"]
    by_chunk = {h["nexus_chunk_id"]: h for h in hits}

    ko1 = by_chunk["chk-1"]["knowledge_outline"]
    assert ko1["node_id"] == "on-1-1"
    assert ko1["title"] == "1.1 概念"
    assert ko1["level"] == 2
    # path is root-first, root (level 0) excluded.
    assert [n["title"] for n in ko1["path"]] == ["第1章 引论", "1.1 概念"]
    assert ko1["path"][-1]["numbering"] == "1.1"

    ko3 = by_chunk["chk-3"]["knowledge_outline"]
    assert ko3["node_id"] == "on-ch2"
    assert [n["title"] for n in ko3["path"]] == ["第2章 应用"]


def test_search_hit_without_outline_has_no_breadcrumb(app, session, monkeypatch):
    _seed_textbook_with_outline(session)
    caller = _seed_caller(session)
    _wire_search_adapter(app, monkeypatch, caller)

    # Detach one chunk from its outline node to simulate a legacy chunk.
    session.execute(
        models.KnowledgeChunk.__table__.update()
        .where(models.KnowledgeChunk.id == "chk-1")
        .values(knowledge_outline_node_id=None)
    )
    session.commit()

    with TestClient(app) as client:
        resp = client.get("/open/v1/search?q=x&kb=textbook_kb&top_k=10")

    assert resp.status_code == 200
    hits = {h["nexus_chunk_id"]: h for h in resp.json()["data"]["results"]}
    assert "knowledge_outline" not in hits["chk-1"]
    # Others still have it.
    assert "knowledge_outline" in hits["chk-2"]


# ---------------------------------------------------------------------------
# Subtree filter
# ---------------------------------------------------------------------------


def test_search_outline_node_filter_restricts_to_subtree(app, session, monkeypatch):
    _seed_textbook_with_outline(session)
    caller = _seed_caller(session)
    _wire_search_adapter(app, monkeypatch, caller)

    with TestClient(app) as client:
        # Filter to 第1章 subtree — chk-1 (1.1) and chk-2 (1.2) qualify.
        resp = client.get(
            "/open/v1/search?q=x&kb=textbook_kb&top_k=10&outline_node=on-ch1"
        )

    assert resp.status_code == 200
    hits = resp.json()["data"]["results"]
    chunk_ids = {h["nexus_chunk_id"] for h in hits}
    assert chunk_ids == {"chk-1", "chk-2"}


def test_search_outline_node_filter_on_leaf(app, session, monkeypatch):
    _seed_textbook_with_outline(session)
    caller = _seed_caller(session)
    _wire_search_adapter(app, monkeypatch, caller)

    with TestClient(app) as client:
        resp = client.get(
            "/open/v1/search?q=x&kb=textbook_kb&top_k=10&outline_node=on-1-1"
        )

    assert resp.status_code == 200
    hits = resp.json()["data"]["results"]
    assert {h["nexus_chunk_id"] for h in hits} == {"chk-1"}


def test_search_outline_node_filter_returns_404_for_missing_node(
    app, session, monkeypatch,
):
    _seed_textbook_with_outline(session)
    caller = _seed_caller(session)
    _wire_search_adapter(app, monkeypatch, caller)

    with TestClient(app) as client:
        resp = client.get(
            "/open/v1/search?q=x&kb=textbook_kb&outline_node=does-not-exist"
        )
    assert resp.status_code == 404
