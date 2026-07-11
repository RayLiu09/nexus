"""PR-6b — verify the write-side tag_asset_index projection hook fires
for each structured domain writer.

Every writer that ships persisted rows through
``project_writer_records`` gets a small integration test here.  Uses
minimal synthetic ``record_body`` payloads instead of the full xlsx
pipeline, so the tests stay <100 ms each and don't depend on B0-B4
plumbing changes.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from nexus_app import models
from nexus_app.domain_normalize import ability_analysis_writer
from nexus_app.domain_normalize import job_demand_writer
from nexus_app.domain_normalize import major_distribution_writer
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
# Scaffolding
# ---------------------------------------------------------------------------


def _seed_scaffold(
    session,
    *,
    ref_id: str,
    asset_kind: AssetKind,
    normalized_type: NormalizedType,
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
        asset_kind=asset_kind, status=AssetVersionStatus.AVAILABLE,
    )
    version = models.AssetVersion(
        id=f"ver-{ref_id}", asset_id=asset.id, raw_object_id=raw.id,
        version_no=1, source_checksum=raw.checksum,
        version_status=AssetVersionStatus.AVAILABLE,
    )
    ref = models.NormalizedAssetRef(
        id=ref_id, version_id=version.id,
        normalized_type=normalized_type,
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


# ---------------------------------------------------------------------------
# job_demand_writer
# ---------------------------------------------------------------------------


class TestJobDemandWriterProjection:
    def test_records_land_tag_asset_index_rows(self, session):
        ref = _seed_scaffold(
            session, ref_id="ref-jd-proj",
            asset_kind=AssetKind.RECORD,
            normalized_type=NormalizedType.RECORD,
            domain_profile="job_demand.v1",
        )
        record_body = {
            "dataset": {
                "major_name": "电子商务",
                "industry_name": "互联网",
                "source_channel": "excel_upload",
                "record_count": 1,
                "invalid_count": 0,
                "duplicate_count": 0,
                "schema_version": "job_demand.v1",
                "quality_summary": {},
            },
            "records": [{
                "source_record_key": "Sheet1#row2",
                "job_title": "电商运营",
                "city": "北京市",
                "industry_name": "直播电商",
                "employment_type": "全职",
                "trace": {"sheet": "Sheet1", "row": 2},
            }],
        }
        result = job_demand_writer.write(session, ref, record_body)
        assert not result.skipped
        assert result.records_written == 1
        tag_rows = list(session.scalars(
            select(models.TagAssetIndex).where(
                models.TagAssetIndex.target_type
                == TagAssetIndexTargetType.JOB_DEMAND_RECORD,
                models.TagAssetIndex.source
                == TagAssetIndexSource.FIELD_PROJECTION,
            )
        ).all())
        assert tag_rows, "no tag_asset_index rows produced"
        buckets = {r.tag_type for r in tag_rows}
        assert "region" in buckets
        assert "industry" in buckets
        assert "occupation" in buckets

    def test_projection_summary_folded_into_audit(self, session):
        ref = _seed_scaffold(
            session, ref_id="ref-jd-audit",
            asset_kind=AssetKind.RECORD,
            normalized_type=NormalizedType.RECORD,
            domain_profile="job_demand.v1",
        )
        job_demand_writer.write(session, ref, {
            "dataset": {
                "major_name": "电子商务", "industry_name": "互联网",
                "source_channel": "excel_upload", "record_count": 1,
                "invalid_count": 0, "duplicate_count": 0,
                "schema_version": "job_demand.v1", "quality_summary": {},
            },
            "records": [{
                "source_record_key": "k",
                "job_title": "电商运营", "city": "北京市",
                "trace": {},
            }],
        })
        from nexus_app.enums import AuditEventType

        audit = session.scalar(
            select(models.AuditLog).where(
                models.AuditLog.event_type
                == AuditEventType.JOB_DEMAND_DATASET_PERSISTED
            )
        )
        assert audit is not None
        assert "tag_projection" in audit.summary
        proj = audit.summary["tag_projection"]
        assert proj["table_name"] == "job_demand_record"
        assert proj["rows_persisted"] >= 1
        assert proj["error"] is None


# ---------------------------------------------------------------------------
# major_distribution_writer
# ---------------------------------------------------------------------------


class TestMajorDistributionWriterProjection:
    def test_records_land_tag_asset_index_rows(self, session):
        ref = _seed_scaffold(
            session, ref_id="ref-md-proj",
            asset_kind=AssetKind.RECORD,
            normalized_type=NormalizedType.RECORD,
            domain_profile="major_distribution.v1",
        )
        record_body = {
            "dataset": {
                "dataset_name": "布点",
                "source_channel": "xlsx",
                "major_scope": "single_major",
                "major_name": "电子商务", "major_code": "530701",
                "education_level": "高职",
                "year_min": 2024, "year_max": 2024,
                "province_count": 1, "record_count": 1,
                "placeholder_count": 0, "ignored_summary_count": 0,
                "invalid_count": 0, "schema_version": "major_distribution.v1",
                "quality_summary": {},
            },
            "records": [{
                "source_record_key": "2024-zj",
                "year": 2024, "province_name": "浙江",
                "major_name": "电子商务", "major_code": "530701",
                "education_level": "高职", "distribution_count": 3,
                "trace": {},
            }],
        }
        result = major_distribution_writer.write(session, ref, record_body)
        assert not result.skipped
        assert result.records_written == 1
        tag_rows = list(session.scalars(
            select(models.TagAssetIndex).where(
                models.TagAssetIndex.target_type
                == TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
                models.TagAssetIndex.source
                == TagAssetIndexSource.FIELD_PROJECTION,
            )
        ).all())
        assert tag_rows, "no tag_asset_index rows produced"
        buckets = {r.tag_type for r in tag_rows}
        assert "region" in buckets
        assert "major" in buckets
        assert result.quality_summary["tag_projection"]["rows_persisted"] >= 1
