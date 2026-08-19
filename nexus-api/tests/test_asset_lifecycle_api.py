import pytest
from fastapi import HTTPException

from nexus_api.api.internal.assets import _require_asset_retirement_role
from nexus_app import asset_lifecycle, models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    AuditEventType,
    DataSourceType,
    IndexManifestStatus,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
    TagAssetIndexSource,
    TagAssetIndexTargetType,
    UserRole,
)


def _seed_asset(session):
    source = models.DataSource(
        id="retire-source",
        code="retire-source",
        name="Retirement source",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="retire-batch",
        data_source_id=source.id,
        idempotency_key="retire-batch-key",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="retire-raw",
        batch_id=batch.id,
        data_source_id=source.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="raw/retirement-source.pdf",
        checksum="sha256:retirement-source",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id="retire-asset",
        data_source_id=source.id,
        source_object_key="retirement-source.pdf",
        title="待废弃资产",
        asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.AVAILABLE,
    )
    version = models.AssetVersion(
        id="retire-version",
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum=raw.checksum,
        version_status=AssetVersionStatus.AVAILABLE,
    )
    ref = models.NormalizedAssetRef(
        id="retire-ref",
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="normalized/retirement-source.json",
        schema_version="normalized-document-v1",
        checksum="sha256:retirement-normalized",
        status=NormalizedAssetRefStatus.GENERATED,
        governance={},
        quality={},
        lineage={},
        metadata_summary={},
    )
    manifest = models.IndexManifest(
        id="retire-manifest",
        normalized_ref_id=ref.id,
        knowledge_type_code="document",
        index_status=IndexManifestStatus.INDEXED,
    )
    tag = models.TagAssetIndex(
        id="retire-tag",
        tag_type="topic",
        tag_value="噪音数据",
        tag_value_normalized="噪音数据",
        target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
        target_id=ref.id,
        asset_version_id=version.id,
        source=TagAssetIndexSource.GOVERNANCE_TAG,
    )
    session.add_all([source, batch, raw, asset, version, ref, manifest, tag])
    session.commit()
    return asset, version, raw, ref, manifest, tag


def test_archive_asset_retains_derivatives_and_writes_audit(session):
    asset, version, raw, ref, manifest, tag = _seed_asset(session)

    response = asset_lifecycle.archive_asset(
        session,
        asset,
        actor_id="expert-1",
        trace_id="trace-archive",
    )

    assert response["status"] == "archived"
    assert session.get(models.Asset, asset.id).status == AssetVersionStatus.ARCHIVED
    assert session.get(models.AssetVersion, version.id).version_status == AssetVersionStatus.ARCHIVED
    assert session.get(models.RawObject, raw.id) is not None
    assert session.get(models.NormalizedAssetRef, ref.id) is not None
    assert session.get(models.IndexManifest, manifest.id) is not None
    assert session.get(models.TagAssetIndex, tag.id) is not None
    assert session.query(models.AuditLog).one().event_type == AuditEventType.ASSET_ARCHIVED


def test_delete_asset_removes_derivatives_and_retains_only_delete_audit(session):
    asset, version, raw, ref, manifest, tag = _seed_asset(session)
    asset_id, version_id, raw_id, ref_id, manifest_id, tag_id = (
        asset.id,
        version.id,
        raw.id,
        ref.id,
        manifest.id,
        tag.id,
    )

    response = asset_lifecycle.delete_asset(
        session,
        asset,
        actor_id="expert-1",
        trace_id="trace-delete",
    )

    assert response["deleted"] is True
    assert session.get(models.Asset, asset_id) is None
    assert session.get(models.AssetVersion, version_id) is None
    assert session.get(models.RawObject, raw_id) is None
    assert session.get(models.NormalizedAssetRef, ref_id) is None
    assert session.get(models.IndexManifest, manifest_id) is None
    assert session.get(models.TagAssetIndex, tag_id) is None
    audits = session.query(models.AuditLog).all()
    assert len(audits) == 1
    assert audits[0].event_type == AuditEventType.ASSET_DELETED
    assert audits[0].target_id == asset_id


def test_asset_retirement_requires_business_expert_or_admin():
    user = models.UserAccount(
        id="retire-ops",
        username="retire-ops",
        display_name="Retire Ops",
        role=UserRole.OPS,
        status="active",
    )

    with pytest.raises(HTTPException, match="business expert") as error:
        _require_asset_retirement_role(user)
    assert error.value.status_code == 403
