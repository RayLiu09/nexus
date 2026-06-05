"""Consumption-side audit tests: `ASSET_VERSION_ACCESSED` on `/open/v1` reads.

Every successful read on the public consumption surface must produce one
`ASSET_VERSION_ACCESSED` row identifying the caller and the lineage triple
(`asset_id`, `version_id`, `normalized_ref_id`). These tests pin the contract
so future endpoint changes don't silently drop the audit.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import auth_service, models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    AuditEventType,
    ChunkType,
    ChunkingStrategy,
    DataSourceType,
    EmbeddingStatus,
    GovernanceResultStatus,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
    SourceKind,
)


# ---------------------------------------------------------------------------
# Fixtures — caller + a single available-version graph reused by every test
# ---------------------------------------------------------------------------

ASSET_ID = "asset-audit-1"
VERSION_ID = "version-audit-1"
REF_ID = "ref-audit-1"
CHUNK_ID = "chunk-audit-1"


@pytest.fixture()
def caller(session: Session) -> tuple[models.ApiCaller, str]:
    plaintext = auth_service.generate_api_caller_key()
    row = models.ApiCaller(
        id="caller-audit-1",
        name="Audit Caller",
        caller_key=None,
        caller_key_hash=auth_service.hash_api_caller_key(plaintext),
        org_scope=[],
        permission_scope=[],
    )
    session.add(row)
    session.commit()
    return row, plaintext


@pytest.fixture()
def available_graph(session: Session) -> None:
    """Seed: 1 data_source → 1 batch → 1 raw → 1 asset → 1 AVAILABLE version → 1 ref → 1 chunk + 1 governance_result."""
    ds = models.DataSource(
        id="ds-audit-1",
        code="ds-audit-1",
        name="Audit DS",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    session.add(ds)
    session.flush()

    batch = models.IngestBatch(
        id="batch-audit-1",
        data_source_id=ds.id,
        idempotency_key="batch-audit-1",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    session.add(batch)
    session.flush()

    raw = models.RawObject(
        id="raw-audit-1",
        batch_id=batch.id,
        data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        source_uri="file://audit",
        object_uri="raw/audit",
        checksum="audit-checksum",
        size_bytes=1,
        status=RawObjectStatus.RAW_PERSISTED,
    )
    session.add(raw)
    session.flush()

    asset = models.DocumentAsset(
        id=ASSET_ID,
        data_source_id=ds.id,
        source_object_key="audit-key",
        title="Audit Asset",
        asset_kind=AssetKind.DOCUMENT,
    )
    session.add(asset)
    session.flush()

    version = models.DocumentVersion(
        id=VERSION_ID,
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum=raw.checksum,
        version_status=AssetVersionStatus.AVAILABLE,
    )
    session.add(version)
    session.flush()

    ref = models.NormalizedAssetRef(
        id=REF_ID,
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="normalized/audit.json",
        schema_version="1.0",
        checksum="ref-audit-checksum",
        title="Audit Doc",
        language="en",
        source_type="file_upload",
        content_type="document",
        governance={"level": "L2"},
        quality={},
        lineage={},
        metadata_summary={},
        status=NormalizedAssetRefStatus.GENERATED,
    )
    session.add(ref)
    session.flush()

    chunk = models.KnowledgeChunk(
        id=CHUNK_ID,
        normalized_ref_id=ref.id,
        knowledge_type_code="passthrough_kb",
        chunk_type=ChunkType.PASSTHROUGH_DESCRIPTOR,
        chunking_strategy=ChunkingStrategy.PASSTHROUGH_TO_RAGFLOW,
        source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
        chunk_index=0,
        content="Audit chunk content",
        chunk_metadata={},
        embedding_status=EmbeddingStatus.EMBEDDED,
    )
    session.add(chunk)
    session.flush()

    governance_result = models.GovernanceResult(
        id="gov-audit-1",
        normalized_ref_id=ref.id,
        status=GovernanceResultStatus.AVAILABLE,
        rules_schema_version="1.0",
        rules_content_hash="audit-rules-hash",
        classification=None,
        level="L2",
        tags=[],
        quality_summary={"overall_score": 0.95},
        decision_trail=[],
    )
    session.add(governance_result)
    session.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _audit_rows(session: Session, *, event: AuditEventType, actor_id: str) -> list[models.AuditLog]:
    return list(
        session.scalars(
            select(models.AuditLog)
            .where(models.AuditLog.event_type == event)
            .where(models.AuditLog.actor_id == actor_id)
            .order_by(models.AuditLog.created_at.asc())
        ).all()
    )


def _summary(row: models.AuditLog) -> dict:
    return row.summary or {}


# ---------------------------------------------------------------------------
# One test per access_type
# ---------------------------------------------------------------------------


def test_asset_detail_emits_audit(app_no_auth_override, session, caller, available_graph):
    row, plaintext = caller
    with TestClient(app_no_auth_override) as client:
        resp = client.get(
            f"/open/v1/assets/{ASSET_ID}",
            headers={"X-API-Key": plaintext},
        )
    assert resp.status_code == 200

    rows = _audit_rows(session, event=AuditEventType.ASSET_VERSION_ACCESSED, actor_id=row.id)
    assert len(rows) == 1
    entry = rows[0]
    assert entry.actor_type == "api_caller"
    assert entry.target_type == "asset"
    assert entry.target_id == ASSET_ID

    summary = _summary(entry)
    assert summary["access_type"] == "asset_detail"
    assert summary["asset_id"] == ASSET_ID
    assert summary["version_id"] == VERSION_ID
    assert summary["normalized_ref_id"] == REF_ID


def test_version_list_emits_audit_with_version_ids(
    app_no_auth_override, session, caller, available_graph
):
    row, plaintext = caller
    with TestClient(app_no_auth_override) as client:
        resp = client.get(
            f"/open/v1/assets/{ASSET_ID}/versions",
            headers={"X-API-Key": plaintext},
        )
    assert resp.status_code == 200

    rows = _audit_rows(session, event=AuditEventType.ASSET_VERSION_ACCESSED, actor_id=row.id)
    assert len(rows) == 1
    summary = _summary(rows[0])
    assert summary["access_type"] == "version_list"
    assert summary["asset_id"] == ASSET_ID
    assert summary["version_ids"] == [VERSION_ID]
    # version_id (singular) should NOT be set for list accesses.
    assert "version_id" not in summary


def test_normalized_ref_emits_audit(app_no_auth_override, session, caller, available_graph):
    row, plaintext = caller
    with TestClient(app_no_auth_override) as client:
        resp = client.get(
            f"/open/v1/normalized-refs/{REF_ID}",
            headers={"X-API-Key": plaintext},
        )
    assert resp.status_code == 200

    rows = _audit_rows(session, event=AuditEventType.ASSET_VERSION_ACCESSED, actor_id=row.id)
    assert len(rows) == 1
    entry = rows[0]
    assert entry.target_type == "normalized_asset_ref"
    assert entry.target_id == REF_ID
    summary = _summary(entry)
    assert summary == {
        "access_type": "normalized_ref",
        "asset_id": ASSET_ID,
        "version_id": VERSION_ID,
        "normalized_ref_id": REF_ID,
    }


def test_governance_result_emits_audit(app_no_auth_override, session, caller, available_graph):
    row, plaintext = caller
    with TestClient(app_no_auth_override) as client:
        resp = client.get(
            f"/open/v1/normalized-refs/{REF_ID}/governance-result",
            headers={"X-API-Key": plaintext},
        )
    assert resp.status_code == 200

    rows = _audit_rows(session, event=AuditEventType.ASSET_VERSION_ACCESSED, actor_id=row.id)
    assert len(rows) == 1
    summary = _summary(rows[0])
    assert summary["access_type"] == "governance_result"
    assert summary["normalized_ref_id"] == REF_ID


def test_knowledge_chunk_emits_audit(app_no_auth_override, session, caller, available_graph):
    row, plaintext = caller
    with TestClient(app_no_auth_override) as client:
        resp = client.get(
            f"/open/v1/knowledge-chunks/{CHUNK_ID}",
            headers={"X-API-Key": plaintext},
        )
    assert resp.status_code == 200

    rows = _audit_rows(session, event=AuditEventType.ASSET_VERSION_ACCESSED, actor_id=row.id)
    assert len(rows) == 1
    entry = rows[0]
    assert entry.target_type == "knowledge_chunk"
    assert entry.target_id == CHUNK_ID
    summary = _summary(entry)
    assert summary == {
        "access_type": "knowledge_chunk",
        "asset_id": ASSET_ID,
        "version_id": VERSION_ID,
        "normalized_ref_id": REF_ID,
    }


def test_open_assets_list_does_not_emit_audit(
    app_no_auth_override, session, caller, available_graph
):
    """List endpoint is intentionally NOT audited (per project decision)."""
    row, plaintext = caller
    with TestClient(app_no_auth_override) as client:
        resp = client.get("/open/v1/assets", headers={"X-API-Key": plaintext})
    assert resp.status_code == 200

    rows = _audit_rows(session, event=AuditEventType.ASSET_VERSION_ACCESSED, actor_id=row.id)
    assert rows == []
