"""Internal console chunk preview endpoints."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from nexus_app import models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    ChunkType,
    ChunkingStrategy,
    DataSourceType,
    EmbeddingStatus,
    IngestBatchStatus,
    RawObjectStatus,
    SourceKind,
)


def _seed_asset(session, *, raw_mime="application/pdf"):
    ds = models.DataSource(
        id="ds-preview", code="ds-preview", name="Preview DS",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="batch-preview", data_source_id=ds.id, idempotency_key="idem-preview",
        source_type=DataSourceType.FILE_UPLOAD, status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="raw-preview", batch_id=batch.id, data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://bucket/raw/sample.pdf",
        checksum="sha256:raw", mime_type=raw_mime,
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id="asset-preview", data_source_id=ds.id, source_object_key="sample.pdf",
        title="Sample", asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.AVAILABLE,
    )
    version = models.AssetVersion(
        id="ver-preview", asset_id=asset.id, raw_object_id=raw.id,
        version_no=1, source_checksum="sha256:raw",
        version_status=AssetVersionStatus.AVAILABLE,
    )
    ref = models.NormalizedAssetRef(
        id="ref-preview", version_id=version.id,
        normalized_type="document",
        object_uri="s3://bucket/normalized/ref-preview.json",
        schema_version="v1", checksum="sha256:norm", status="generated",
        block_count=2, record_count=0,
        governance={}, quality={}, lineage={}, metadata_summary={},
    )
    session.add_all([ds, batch, raw, asset, version, ref])
    session.commit()
    return raw, asset, version, ref


def _make_chunk(ref_id: str) -> models.KnowledgeChunk:
    return models.KnowledgeChunk(
        id="chunk-preview",
        normalized_ref_id=ref_id,
        knowledge_type_code="industry_research_kb",
        chunk_type=ChunkType.SEMANTIC_BLOCK,
        chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK,
        source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
        chunk_index=0,
        content="chunk body",
        chunk_metadata={"anchor_role": "table_row", "table_row_index": 1},
        embedding_status=EmbeddingStatus.PENDING,
        source_block_ids=["tbl-1"],
        locator={
            "page_start": 5,
            "page_end": 5,
            "bbox_union": [10, 20, 100, 80],
            "md_char_range": [30, 70],
            "md_spans": None,
            "heading_path": [{"level": 1, "title": "政策"}],
            "blocks": [
                {
                    "block_id": "tbl-1",
                    "page": 5,
                    "bbox": [10, 20, 100, 80],
                    "md_char_range": [30, 70],
                }
            ],
        },
    )


def _context_chunk(
    ref_id: str,
    *,
    chunk_id: str,
    index: int,
    content: str,
    anchor_role: str = "body",
    heading_title: str = "政策",
    source_block_id: str | None = None,
    extra_meta: dict | None = None,
) -> models.KnowledgeChunk:
    metadata = {"anchor_role": anchor_role}
    if extra_meta:
        metadata.update(extra_meta)
    return models.KnowledgeChunk(
        id=chunk_id,
        normalized_ref_id=ref_id,
        knowledge_type_code="industry_research_kb",
        chunk_type=ChunkType.SEMANTIC_BLOCK,
        chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK,
        source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
        chunk_index=index,
        content=content,
        chunk_metadata=metadata,
        embedding_status=EmbeddingStatus.PENDING,
        source_block_ids=[source_block_id or f"block-{index}"],
        locator={
            "page_start": 1,
            "page_end": 1,
            "bbox_union": None,
            "md_char_range": [index * 10, index * 10 + 5],
            "md_spans": None,
            "heading_path": [{"level": 1, "title": heading_title}],
            "blocks": [
                {
                    "block_id": source_block_id or f"block-{index}",
                    "page": 1,
                    "bbox": None,
                    "md_char_range": [index * 10, index * 10 + 5],
                }
            ],
        },
    )


class TestInternalChunkPreview:
    def test_preview_returns_chunk_source_and_highlight(self, app, session, monkeypatch):
        _, _, _, ref = _seed_asset(session)
        chunk = _make_chunk(ref.id)
        session.add(chunk)
        session.commit()

        payload = {
            "body_markdown": "# 政策\n\n表格内容第一行\n\n尾部",
            "blocks": [
                {"block_id": "tbl-1", "block_type": "table", "page": 5,
                 "bbox": [10, 20, 100, 80], "md_char_range": [30, 70]},
            ],
        }

        class FakeStorage:
            def get_bytes(self, key):
                assert key == "normalized/ref-preview.json"
                return json.dumps(payload).encode("utf-8")

        monkeypatch.setattr("nexus_app.storage.get_object_storage", lambda settings=None: FakeStorage())

        client = TestClient(app)
        resp = client.get(f"/internal/v1/knowledge-chunks/{chunk.id}/preview")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["chunk"]["id"] == chunk.id
        assert data["source"]["body_markdown"] == payload["body_markdown"]
        assert data["highlight"]["markdown_ranges"] == [
            {"start": 30, "end": 70, "block_id": None}
        ]
        assert data["highlight"]["page_anchors"] == [
            {"page": 5, "bbox": [10, 20, 100, 80], "block_id": "tbl-1"}
        ]
        assert data["highlight"]["heading_path"] == [{"level": 1, "title": "政策"}]
        assert data["highlight"]["anchor_role"] == "table_row"

    def test_preview_prefers_md_spans_when_present(self, app, session, monkeypatch):
        _, _, _, ref = _seed_asset(session)
        chunk = _make_chunk(ref.id)
        chunk.locator = {
            **chunk.locator,
            "md_spans": [
                {"start": 1, "end": 3, "block_id": "a"},
                {"start": 5, "end": 9, "block_id": "b"},
            ],
        }
        session.add(chunk)
        session.commit()

        class FakeStorage:
            def get_bytes(self, key):  # noqa: ARG002
                return json.dumps({"body_markdown": "abcdefghi", "blocks": []}).encode("utf-8")

        monkeypatch.setattr("nexus_app.storage.get_object_storage", lambda settings=None: FakeStorage())

        client = TestClient(app)
        resp = client.get(f"/internal/v1/knowledge-chunks/{chunk.id}/preview")
        assert resp.status_code == 200
        assert resp.json()["data"]["highlight"]["markdown_ranges"] == [
            {"start": 1, "end": 3, "block_id": "a"},
            {"start": 5, "end": 9, "block_id": "b"},
        ]

    def test_page_image_rejects_non_pdf_raw_object(self, app, session):
        _, _, _, ref = _seed_asset(session, raw_mime="text/plain")
        client = TestClient(app)
        resp = client.get(f"/internal/v1/normalized-refs/{ref.id}/page-image?page=0")
        assert resp.status_code == 415

    def test_page_image_validates_bbox_shape(self, app, session):
        _, _, _, ref = _seed_asset(session)
        client = TestClient(app)
        resp = client.get(f"/internal/v1/normalized-refs/{ref.id}/page-image?page=0&bbox=1,2,3")
        assert resp.status_code == 422

    def test_semantic_context_returns_neighbors_section_and_table_overview(self, app, session):
        _, _, _, ref = _seed_asset(session)
        chunks = [
            _context_chunk(ref.id, chunk_id="ctx-prev", index=0, content="前文"),
            _context_chunk(
                ref.id,
                chunk_id="ctx-overview",
                index=1,
                content="表格概览",
                anchor_role="table_overview",
                extra_meta={"table_parent_block_id": "tbl-main"},
            ),
            _context_chunk(
                ref.id,
                chunk_id="ctx-current",
                index=2,
                content="表格行",
                anchor_role="table_row",
                extra_meta={"table_parent_block_id": "tbl-main", "table_row_index": 1},
            ),
            _context_chunk(
                ref.id,
                chunk_id="ctx-next",
                index=3,
                content="后文",
            ),
            _context_chunk(
                ref.id,
                chunk_id="ctx-other-section",
                index=4,
                content="其它章节",
                heading_title="其它政策",
            ),
        ]
        session.add_all(chunks)
        session.commit()

        client = TestClient(app)
        resp = client.get("/internal/v1/knowledge-chunks/ctx-current/semantic-context")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["chunk"]["id"] == "ctx-current"
        context = data["context"]
        assert context["neighbors"]["previous"][0]["id"] == "ctx-overview"
        assert context["neighbors"]["next"][0]["id"] == "ctx-next"
        assert context["table"]["overview"]["id"] == "ctx-overview"
        sibling_ids = {item["id"] for item in context["section"]["siblings"]}
        assert "ctx-prev" in sibling_ids
        assert "ctx-next" in sibling_ids
        assert "ctx-other-section" not in sibling_ids
        assert context["policy"]["source"] == "internal_console"

    def test_semantic_context_returns_media_nearby_body_chunks(self, app, session):
        _, _, _, ref = _seed_asset(session)
        session.add_all([
            _context_chunk(ref.id, chunk_id="media-body-prev", index=0, content="图前说明"),
            _context_chunk(
                ref.id,
                chunk_id="media-current",
                index=1,
                content="图 1",
                anchor_role="image",
            ),
            _context_chunk(ref.id, chunk_id="media-body-next", index=2, content="图后解释"),
        ])
        session.commit()

        client = TestClient(app)
        resp = client.get("/internal/v1/knowledge-chunks/media-current/semantic-context")
        assert resp.status_code == 200
        nearby = resp.json()["data"]["context"]["media"]["nearby_body_chunks"]
        assert [item["id"] for item in nearby] == ["media-body-prev", "media-body-next"]
