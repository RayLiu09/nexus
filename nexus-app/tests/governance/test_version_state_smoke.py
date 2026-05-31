"""Smoke test for VersionStateManager unique-available + archive-old transition."""
from __future__ import annotations

from nexus_app import models
from nexus_app.enums import (
    AssetVersionStatus,
    AuditEventType,
    DataSourceType,
    GovernanceResultStatus,
)
from nexus_app.metadata.version_state import VersionStateManager


_vs_counter = 0


def _seed_asset_with_versions(session, num_versions: int):
    global _vs_counter
    _vs_counter += 1
    n = _vs_counter
    from nexus_app.enums import AssetKind, IngestBatchStatus, RawObjectStatus
    source = models.DataSource(
        code=f"ds-vs-{n}", name="vs", source_type=DataSourceType.FILE_UPLOAD,
    )
    session.add(source)
    session.flush()
    batch = models.IngestBatch(
        data_source_id=source.id,
        idempotency_key=f"vs-key-{n}",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    session.add(batch)
    session.flush()
    asset = models.DocumentAsset(
        data_source_id=source.id,
        source_object_key=f"key-{n}",
        title=f"asset-{n}",
        asset_kind=AssetKind.DOCUMENT,
    )
    session.add(asset)
    session.flush()
    versions = []
    for i in range(num_versions):
        raw = models.RawObject(
            data_source_id=source.id, batch_id=batch.id,
            object_uri=f"s3://b/k-{n}-{i}", checksum=f"chk-{n}-{i}",
            source_type=DataSourceType.FILE_UPLOAD,
            mime_type="application/pdf", size_bytes=100,
            status=RawObjectStatus.RAW_PERSISTED,
        )
        session.add(raw)
        session.flush()
        v = models.DocumentVersion(
            asset_id=asset.id,
            raw_object_id=raw.id,
            version_no=i + 1,
            source_checksum=f"chk-{n}-{i}",
            version_status=AssetVersionStatus.AVAILABLE if i == 0 else AssetVersionStatus.PROCESSING,
        )
        session.add(v)
        versions.append(v)
    session.commit()
    return asset, versions


def _passing_result(version):
    return models.GovernanceResult(
        normalized_ref_id="ref-x",
        ai_run_id="run-x",
        classification="D1",
        level="L1",
        tags=[],
        index_admission=True,
        quality_summary={"quality_level": "pass", "quality_score": 90.0},
        decision_trail=[
            {"field_name": "classification", "adoption_status": "auto_adopted"},
            {"field_name": "level", "adoption_status": "auto_adopted"},
            {"field_name": "tags", "adoption_status": "auto_adopted"},
            {"field_name": "quality", "adoption_status": "auto_adopted"},
        ],
        rules_schema_version="1.0",
        rules_content_hash="abcd1234",
        status=GovernanceResultStatus.AVAILABLE,
    )


class TestVersionStateManager:
    def test_transition_archives_old_available(self, session):
        asset, [v1, v2] = _seed_asset_with_versions(session, 2)
        result = _passing_result(v2)
        session.add(result)
        session.commit()
        VersionStateManager().transition_to_available(session, v2, result)
        session.refresh(v1)
        session.refresh(v2)
        assert v1.version_status == AssetVersionStatus.ARCHIVED
        assert v2.version_status == AssetVersionStatus.AVAILABLE

    def test_admission_blocked_when_quality_fail(self, session):
        from nexus_app.metadata.version_state import StateTransitionError
        asset, [v1] = _seed_asset_with_versions(session, 1)
        v1.version_status = AssetVersionStatus.PROCESSING
        result = _passing_result(v1)
        result.quality_summary = {"quality_level": "fail", "quality_score": 30.0}
        session.add(result)
        session.commit()
        try:
            VersionStateManager().transition_to_available(session, v1, result)
            assert False, "expected StateTransitionError"
        except StateTransitionError:
            pass
