"""Tests for the lineage-facing endpoints:
    GET /open/v1/normalized-refs/{ref_id}/chunks
    GET /open/v1/raw-objects/{raw_object_id}/download-url

Also covers the top-level surfacing of `primary_block_ids` / `evidence_block_ids`
from `chunk_metadata` on the single-chunk endpoint and on search/qa hits.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_app import models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    AuditEventType,
    ChunkType,
    ChunkingStrategy as ChunkingStrategyEnum,
    DataSourceType,
    EmbeddingStatus,
    IngestBatchStatus,
    RawObjectStatus,
    SourceKind,
)


def _seed_caller(session) -> models.ApiCaller:
    caller = models.ApiCaller(
        caller_key="lineage-test-caller",
        name="Lineage Test",
        org_scope=["org-1"],
        permission_scope=[],
    )
    session.add(caller)
    session.commit()
    return caller


def _seed_minimal_asset(session, *, ds_id="ds-x", raw_id="raw-x",
                       asset_id="asset-x", version_id="ver-x", ref_id="ref-x",
                       object_uri="s3://nexus-raw/lineage/sample.pdf"):
    ds = models.DataSource(
        id=ds_id, code=ds_id, name="DS",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="batch-x", data_source_id=ds_id, idempotency_key="idem",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id=raw_id, batch_id="batch-x", data_source_id=ds_id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri=object_uri,
        checksum="sha256:abc",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id=asset_id, data_source_id=ds_id, source_object_key="sample.pdf",
        title="Sample", asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.AVAILABLE,
    )
    version = models.AssetVersion(
        id=version_id, asset_id=asset_id, raw_object_id=raw_id,
        version_no=1, source_checksum="sha256:abc",
        version_status=AssetVersionStatus.AVAILABLE,
    )
    ref = models.NormalizedAssetRef(
        id=ref_id, version_id=version_id,
        normalized_type="document",
        object_uri=f"s3://nexus-norm/{ref_id}.json",
        schema_version="v1",
        checksum="sha256:def",
        status="generated",
        block_count=2, record_count=0,
        governance={}, quality={}, lineage={}, metadata_summary={},
    )
    session.add_all([ds, batch, raw, asset, version, ref])
    session.commit()
    return ds, raw, asset, version, ref


def _make_chunk(
    ref_id: str, idx: int, *,
    locator: dict | None = None,
    source_block_ids: list[str] | None = None,
    metadata: dict | None = None,
) -> models.KnowledgeChunk:
    return models.KnowledgeChunk(
        normalized_ref_id=ref_id,
        knowledge_type_code="kt_doc",
        chunk_type=ChunkType.PASSTHROUGH_DESCRIPTOR,
        chunking_strategy=ChunkingStrategyEnum.PASSTHROUGH_TO_RAGFLOW,
        source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
        chunk_index=idx,
        content=f"chunk-{idx}",
        chunk_metadata=metadata or {},
        ragflow_chunk_method="naive",
        embedding_status=EmbeddingStatus.PENDING,
        source_block_ids=source_block_ids,
        locator=locator,
    )


def _override_caller(app, caller):
    from nexus_api.auth import require_api_caller
    app.dependency_overrides[require_api_caller] = lambda: caller


# ---------- GET /normalized-refs/{ref_id}/chunks ----------

class TestChunksByRefEndpoint:
    def test_returns_paginated_chunks_with_locator(self, app, session):
        caller = _seed_caller(session)
        _, _, _, _, ref = _seed_minimal_asset(session)

        for i in range(3):
            session.add(_make_chunk(
                ref.id, i,
                locator={"page_start": i + 1, "page_end": i + 1,
                         "bbox_union": None, "blocks": []},
                source_block_ids=[f"b{i}"],
            ))
        session.commit()
        _override_caller(app, caller)

        client = TestClient(app)
        resp = client.get(f"/open/v1/normalized-refs/{ref.id}/chunks?pageSize=2")
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 3
        assert len(body["data"]) == 2
        first = body["data"][0]
        # Stage 2.2 fields surface at top level
        assert first["locator"]["page_start"] == 1
        assert first["source_block_ids"] == ["b0"]
        # Stage 2.4 fields absent for non-graph chunks
        assert "primary_block_ids" not in first
        assert "evidence_block_ids" not in first

    def test_graph_extract_chunk_surfaces_primary_and_evidence(self, app, session):
        caller = _seed_caller(session)
        _, _, _, _, ref = _seed_minimal_asset(session)

        session.add(_make_chunk(
            ref.id, 0,
            locator={"page_start": 1, "page_end": 1,
                     "bbox_union": None, "blocks": []},
            source_block_ids=["b1", "b2"],
            metadata={
                "primary_block_ids": ["b1"],
                "evidence_block_ids": ["b2"],
            },
        ))
        session.commit()
        _override_caller(app, caller)

        client = TestClient(app)
        resp = client.get(f"/open/v1/normalized-refs/{ref.id}/chunks")
        body = resp.json()
        first = body["data"][0]
        assert first["primary_block_ids"] == ["b1"]
        assert first["evidence_block_ids"] == ["b2"]

    def test_404_when_ref_unavailable(self, app, session):
        caller = _seed_caller(session)
        _override_caller(app, caller)
        client = TestClient(app)
        resp = client.get("/open/v1/normalized-refs/nope/chunks")
        assert resp.status_code == 404

    def test_writes_chunk_list_audit_event(self, app, session):
        caller = _seed_caller(session)
        _, _, _, _, ref = _seed_minimal_asset(session)
        session.add(_make_chunk(ref.id, 0))
        session.commit()
        _override_caller(app, caller)

        client = TestClient(app)
        client.get(f"/open/v1/normalized-refs/{ref.id}/chunks")
        events = list(session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.event_type == AuditEventType.ASSET_VERSION_ACCESSED
            )
        ))
        assert events
        assert events[-1].summary["access_type"] == "chunk_list"


# ---------- GET /raw-objects/{id}/download-url ----------

class TestRawDownloadUrlEndpoint:
    def test_returns_presigned_url(self, app, session, monkeypatch):
        caller = _seed_caller(session)
        _, raw, _, version, _ = _seed_minimal_asset(session)

        # Patch get_object_storage to a fake that returns a deterministic URL.
        from datetime import datetime, timedelta, timezone
        from nexus_app.storage import PresignedDownload
        class FakeStorage:
            def generate_presigned_download(self, key, *, ttl_seconds=900):
                return PresignedDownload(
                    download_url=f"https://example.test/{key}?ttl={ttl_seconds}",
                    expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
                )
        monkeypatch.setattr(
            "nexus_app.storage.get_object_storage",
            lambda settings=None: FakeStorage(),
        )
        _override_caller(app, caller)

        client = TestClient(app)
        resp = client.get(
            f"/open/v1/raw-objects/{raw.id}/download-url?ttl_seconds=600"
        )
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["raw_object_id"] == raw.id
        assert "lineage/sample.pdf?ttl=600" in body["download_url"]
        assert body["ttl_seconds"] == 600
        # ISO 8601 expires_at returned
        assert body["expires_at"].endswith("+00:00") or body["expires_at"].endswith("Z")

    def test_404_when_raw_missing(self, app, session, monkeypatch):
        caller = _seed_caller(session)
        _override_caller(app, caller)
        client = TestClient(app)
        resp = client.get("/open/v1/raw-objects/no-such-id/download-url")
        assert resp.status_code == 404

    def test_404_when_no_available_version_references_raw(self, app, session):
        caller = _seed_caller(session)
        # Create raw but mark version as processing (not AVAILABLE)
        ds = models.DataSource(
            id="ds-q", code="ds-q", name="Q",
            source_type=DataSourceType.FILE_UPLOAD,
        )
        batch = models.IngestBatch(
            id="batch-q", data_source_id="ds-q", idempotency_key="iq",
            source_type=DataSourceType.FILE_UPLOAD,
            status=IngestBatchStatus.COMPLETED,
        )
        raw = models.RawObject(
            id="raw-q", batch_id="batch-q", data_source_id="ds-q",
            source_type=DataSourceType.FILE_UPLOAD,
            object_uri="s3://nexus-raw/q.pdf",
            checksum="sha256:q",
            status=RawObjectStatus.RAW_PERSISTED,
        )
        asset = models.Asset(
            id="asset-q", data_source_id="ds-q", source_object_key="q.pdf",
            title="Q", asset_kind=AssetKind.DOCUMENT,
            status=AssetVersionStatus.PROCESSING,
        )
        version = models.AssetVersion(
            id="ver-q", asset_id="asset-q", raw_object_id="raw-q",
            version_no=1, source_checksum="sha256:q",
            version_status=AssetVersionStatus.PROCESSING,  # not AVAILABLE
        )
        session.add_all([ds, batch, raw, asset, version])
        session.commit()
        _override_caller(app, caller)

        client = TestClient(app)
        resp = client.get(f"/open/v1/raw-objects/{raw.id}/download-url")
        assert resp.status_code == 404

    def test_ttl_query_bounds(self, app, session):
        caller = _seed_caller(session)
        _, raw, _, _, _ = _seed_minimal_asset(session)
        _override_caller(app, caller)
        client = TestClient(app)
        # below minimum
        resp = client.get(f"/open/v1/raw-objects/{raw.id}/download-url?ttl_seconds=30")
        assert resp.status_code == 422
        # above maximum
        resp = client.get(f"/open/v1/raw-objects/{raw.id}/download-url?ttl_seconds=9999")
        assert resp.status_code == 422

    def test_writes_raw_download_audit_event(self, app, session, monkeypatch):
        caller = _seed_caller(session)
        _, raw, _, _, _ = _seed_minimal_asset(session)
        from datetime import datetime, timezone
        from nexus_app.storage import PresignedDownload
        class FakeStorage:
            def generate_presigned_download(self, key, *, ttl_seconds=900):
                return PresignedDownload(
                    download_url="https://example.test/x",
                    expires_at=datetime.now(timezone.utc),
                )
        monkeypatch.setattr(
            "nexus_app.storage.get_object_storage",
            lambda settings=None: FakeStorage(),
        )
        _override_caller(app, caller)

        client = TestClient(app)
        client.get(f"/open/v1/raw-objects/{raw.id}/download-url")
        events = list(session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.event_type == AuditEventType.ASSET_VERSION_ACCESSED
            )
        ))
        assert events
        assert events[-1].summary["access_type"] == "raw_download"


# ---------- single chunk endpoint top-level surfacing ----------

class TestSingleChunkSurfacing:
    def test_single_chunk_surfaces_locator_and_graph_fields(self, app, session):
        caller = _seed_caller(session)
        _, _, _, _, ref = _seed_minimal_asset(session)
        chunk = _make_chunk(
            ref.id, 0,
            locator={"page_start": 2, "page_end": 3,
                     "bbox_union": None, "blocks": []},
            source_block_ids=["b1", "b2", "b3"],
            metadata={
                "primary_block_ids": ["b1"],
                "evidence_block_ids": ["b2", "b3"],
            },
        )
        session.add(chunk)
        session.commit()
        _override_caller(app, caller)

        client = TestClient(app)
        resp = client.get(f"/open/v1/knowledge-chunks/{chunk.id}")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["locator"]["page_start"] == 2
        assert body["source_block_ids"] == ["b1", "b2", "b3"]
        assert body["primary_block_ids"] == ["b1"]
        assert body["evidence_block_ids"] == ["b2", "b3"]


# ---------- GET /normalized-refs/{ref_id}/content ----------

class TestNormalizedRefContent:
    """The /content endpoint reads the normalized payload from MinIO and
    returns body_markdown + blocks (document) or record_body (record).

    The byte-stability invariant is critical: any frontend that splits
    body_markdown by md_char_range must receive bytes identical to what
    the parse pipeline persisted — otherwise block anchors drift.
    """

    _DOC_PAYLOAD = {
        "body_markdown": "# Title\n\nHello world.\n\nTail.",
        "blocks": [
            {"block_id": "block-001", "block_type": "heading",
             "page": 0, "bbox": [10, 10, 100, 30],
             "md_char_range": [0, 7]},
            {"block_id": "block-002", "block_type": "paragraph",
             "page": 0, "bbox": [10, 40, 100, 80],
             "md_char_range": [9, 21]},
            {"block_id": "block-003", "block_type": "paragraph",
             "page": 1, "bbox": [10, 10, 100, 30],
             "md_char_range": [23, 28]},
        ],
    }

    def test_returns_body_markdown_and_blocks_byte_identical(
        self, app, session, monkeypatch,
    ):
        import json as _json

        caller = _seed_caller(session)
        _, _, _, _, ref = _seed_minimal_asset(session)

        captured_bytes = _json.dumps(self._DOC_PAYLOAD).encode("utf-8")

        class FakeStorage:
            def get_bytes(self, key):  # noqa: ARG002
                return captured_bytes

        monkeypatch.setattr(
            "nexus_app.storage.get_object_storage",
            lambda settings=None: FakeStorage(),
        )
        _override_caller(app, caller)

        client = TestClient(app)
        resp = client.get(f"/open/v1/normalized-refs/{ref.id}/content")
        assert resp.status_code == 200
        body = resp.json()["data"]

        # Byte identity — the most important assertion. Any drift here
        # would silently misalign the frontend block-anchor splitter.
        assert body["body_markdown"] == self._DOC_PAYLOAD["body_markdown"]
        assert body["blocks"] == self._DOC_PAYLOAD["blocks"]
        assert body["normalized_type"] == "document"
        assert body["record_body"] is None

    def test_record_type_returns_record_body(
        self, app, session, monkeypatch,
    ):
        import json as _json
        from nexus_app import models as nexus_models
        from nexus_app.enums import (
            AssetKind as AK,
            AssetVersionStatus as AVS,
            DataSourceType as DST,
            IngestBatchStatus as IBS,
            RawObjectStatus as ROS,
        )

        caller = _seed_caller(session)
        # Build a record-type ref
        ds = nexus_models.DataSource(
            id="ds-r", code="ds-r", name="R", source_type=DST.WEBHOOK,
        )
        batch = nexus_models.IngestBatch(
            id="batch-r", data_source_id="ds-r", idempotency_key="ir",
            source_type=DST.WEBHOOK, status=IBS.COMPLETED,
        )
        raw = nexus_models.RawObject(
            id="raw-r", batch_id="batch-r", data_source_id="ds-r",
            source_type=DST.WEBHOOK,
            object_uri="s3://nexus-raw/r.json",
            checksum="sha256:r",
            status=ROS.RAW_PERSISTED,
        )
        asset = nexus_models.Asset(
            id="asset-r", data_source_id="ds-r", source_object_key="r.json",
            title="R", asset_kind=AK.RECORD,
            status=AVS.AVAILABLE,
        )
        version = nexus_models.AssetVersion(
            id="ver-r", asset_id="asset-r", raw_object_id="raw-r",
            version_no=1, source_checksum="sha256:r",
            version_status=AVS.AVAILABLE,
        )
        ref = nexus_models.NormalizedAssetRef(
            id="ref-r", version_id="ver-r",
            normalized_type="record",
            object_uri="s3://nexus-norm/ref-r.json",
            schema_version="v1",
            checksum="sha256:rec",
            status="generated",
            block_count=0, record_count=1,
            governance={}, quality={}, lineage={}, metadata_summary={},
        )
        session.add_all([ds, batch, raw, asset, version, ref])
        session.commit()

        record_payload = {"record_body": {"name": "alice", "age": 30}}

        class FakeStorage:
            def get_bytes(self, key):  # noqa: ARG002
                return _json.dumps(record_payload).encode("utf-8")

        monkeypatch.setattr(
            "nexus_app.storage.get_object_storage",
            lambda settings=None: FakeStorage(),
        )
        _override_caller(app, caller)

        client = TestClient(app)
        resp = client.get(f"/open/v1/normalized-refs/{ref.id}/content")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["normalized_type"] == "record"
        assert body["body_markdown"] is None
        assert body["blocks"] is None
        assert body["record_body"] == {"name": "alice", "age": 30}

    def test_404_when_ref_not_available(self, app, session):
        caller = _seed_caller(session)
        _override_caller(app, caller)
        client = TestClient(app)
        resp = client.get("/open/v1/normalized-refs/nope/content")
        assert resp.status_code == 404

    def test_503_when_storage_unavailable(self, app, session, monkeypatch):
        from nexus_app.storage import ObjectStorageError

        caller = _seed_caller(session)
        _, _, _, _, ref = _seed_minimal_asset(session)

        class FakeStorage:
            def get_bytes(self, key):  # noqa: ARG002
                raise ObjectStorageError("transient")

        monkeypatch.setattr(
            "nexus_app.storage.get_object_storage",
            lambda settings=None: FakeStorage(),
        )
        _override_caller(app, caller)

        client = TestClient(app)
        resp = client.get(f"/open/v1/normalized-refs/{ref.id}/content")
        assert resp.status_code == 503

    def test_writes_normalized_ref_audit_event(
        self, app, session, monkeypatch,
    ):
        import json as _json

        caller = _seed_caller(session)
        _, _, _, _, ref = _seed_minimal_asset(session)

        class FakeStorage:
            def get_bytes(self, key):  # noqa: ARG002
                return _json.dumps(self._payload()).encode("utf-8")

            def _payload(self):
                return {"body_markdown": "x", "blocks": []}

        monkeypatch.setattr(
            "nexus_app.storage.get_object_storage",
            lambda settings=None: FakeStorage(),
        )
        _override_caller(app, caller)

        client = TestClient(app)
        client.get(f"/open/v1/normalized-refs/{ref.id}/content")
        events = list(session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.event_type == AuditEventType.ASSET_VERSION_ACCESSED
            )
        ))
        assert events
        assert events[-1].summary["access_type"] == "normalized_ref"
