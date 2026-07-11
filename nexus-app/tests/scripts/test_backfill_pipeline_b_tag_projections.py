"""Regression coverage for the PR-6b backfill script."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from nexus_app import models
from scripts.backfill_pipeline_b_tag_projections import (
    _DOMAINS,
    run_backfill,
)
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
    TagAssetIndexSource,
    TagAssetIndexTargetType,
)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_scaffold(
    session,
    *,
    ref_id: str,
    domain_profile: str,
) -> models.NormalizedAssetRef:
    ds = models.DataSource(
        id=f"ds-{ref_id}", code=f"ds-{ref_id}", name="src",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id=f"batch-{ref_id}", data_source_id=ds.id,
        idempotency_key=f"idem-{ref_id}",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id=f"raw-{ref_id}", batch_id=batch.id, data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri=f"s3://x/{ref_id}", checksum=f"cs-{ref_id}",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id=f"asset-{ref_id}", data_source_id=ds.id,
        source_object_key=ref_id, title="fixture",
        asset_kind=AssetKind.RECORD,
        status=AssetVersionStatus.AVAILABLE,
    )
    version = models.AssetVersion(
        id=f"ver-{ref_id}", asset_id=asset.id, raw_object_id=raw.id,
        version_no=1, source_checksum=raw.checksum,
        version_status=AssetVersionStatus.AVAILABLE,
    )
    ref = models.NormalizedAssetRef(
        id=ref_id, version_id=version.id,
        normalized_type=NormalizedType.RECORD,
        object_uri=f"s3://x/{ref_id}.json",
        schema_version="normalized-record.v2",
        checksum=f"nrm-{ref_id}",
        status=NormalizedAssetRefStatus.GENERATED,
        source_type="file_upload", content_type="table_sheet",
        title="fixture", language="zh-CN",
        governance={}, quality={}, lineage={},
        metadata_summary={"domain_profile": domain_profile},
    )
    session.add_all([ds, batch, raw, asset, version, ref])
    session.flush()
    return ref


def _seed_job_demand_dataset_without_tags(session) -> str:
    """Legacy dataset: records exist, no tag_asset_index rows.  This
    simulates the pre-PR-6b state on production DBs."""
    ref = _seed_scaffold(
        session, ref_id="ref-jd-legacy",
        domain_profile="job_demand.v1",
    )
    dataset = models.JobDemandDataset(
        id="ds-jd-legacy", normalized_ref_id=ref.id,
        asset_version_id=ref.version_id,
        source_channel="excel_upload",
        major_name="电子商务", industry_name="直播电商",
        record_count=1, schema_version="job_demand.v1", quality_summary={},
    )
    session.add(dataset)
    session.flush()
    record = models.JobDemandRecord(
        id="record-jd-legacy", dataset_id=dataset.id,
        normalized_ref_id=ref.id,
        source_record_key="legacy", job_title="电商运营",
        city="北京市", industry_name="直播电商",
        record_fingerprint="fp-legacy",
        quality_flags={}, trace={},
    )
    session.add(record)
    session.commit()
    return dataset.id


def _tag_rows_for(session, target_id: str) -> list[models.TagAssetIndex]:
    return list(session.scalars(
        select(models.TagAssetIndex).where(
            models.TagAssetIndex.target_id == target_id,
            models.TagAssetIndex.source
            == TagAssetIndexSource.FIELD_PROJECTION,
        )
    ).all())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBackfillJobDemand:
    def test_dry_run_reports_but_does_not_persist(self, session):
        _seed_job_demand_dataset_without_tags(session)
        assert _tag_rows_for(session, "record-jd-legacy") == []
        outcomes = run_backfill(
            session=session,
            domains=["job_demand"],
            dataset_ids=None,
            apply=False,
        )
        assert outcomes["job_demand"].datasets_seen == 1
        assert outcomes["job_demand"].total_rows_persisted >= 3  # region/industry/occupation
        # Dry-run rolled back — no tag rows persisted.
        assert _tag_rows_for(session, "record-jd-legacy") == []

    def test_apply_persists_rows(self, session):
        _seed_job_demand_dataset_without_tags(session)
        assert _tag_rows_for(session, "record-jd-legacy") == []
        outcomes = run_backfill(
            session=session,
            domains=["job_demand"],
            dataset_ids=None,
            apply=True,
        )
        assert outcomes["job_demand"].datasets_ok == 1
        rows = _tag_rows_for(session, "record-jd-legacy")
        assert rows, "expected tag_asset_index rows after apply"
        buckets = {r.tag_type for r in rows}
        assert "region" in buckets
        assert "industry" in buckets
        assert "occupation" in buckets

    def test_reapply_is_idempotent(self, session):
        _seed_job_demand_dataset_without_tags(session)
        run_backfill(
            session=session, domains=["job_demand"],
            dataset_ids=None, apply=True,
        )
        first_count = len(_tag_rows_for(session, "record-jd-legacy"))
        # Re-run — same count expected (delete-then-insert per triple).
        run_backfill(
            session=session, domains=["job_demand"],
            dataset_ids=None, apply=True,
        )
        second_count = len(_tag_rows_for(session, "record-jd-legacy"))
        assert first_count == second_count

    def test_dataset_ids_narrow_scope(self, session):
        dataset_id = _seed_job_demand_dataset_without_tags(session)
        outcomes = run_backfill(
            session=session,
            domains=["job_demand"],
            dataset_ids={"non-existent-uuid"},
            apply=False,
        )
        assert outcomes["job_demand"].datasets_seen == 0

        outcomes = run_backfill(
            session=session,
            domains=["job_demand"],
            dataset_ids={dataset_id},
            apply=False,
        )
        assert outcomes["job_demand"].datasets_seen == 1


class TestBackfillDomainRegistry:
    def test_all_writer_tables_covered(self):
        # Ensure the backfill covers every domain the writer hook
        # supports.  If a new writer joins tag_projection_hook, this
        # test flags the gap immediately.
        assert set(_DOMAINS.keys()) == {
            "job_demand", "major_distribution", "ability_analysis",
        }
