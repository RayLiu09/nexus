from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from nexus_app import models
from nexus_app.domain_normalize import dispatch_domain_normalize
from nexus_app.domain_normalize.major_distribution_writer import write
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
)
from nexus_app.profile_detect import detect
from nexus_app.storage import InMemoryObjectStorage
from nexus_app.structured_parse import parse_xlsx
from nexus_app.structured_parse.record_body_adapter import project_to_record_body

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_MAJOR_MULTI = REPO_ROOT / "docs/samples/2.（专业布点数）专业布点数.xlsx"
SAMPLE_MAJOR_ECOMMERCE = REPO_ROOT / "docs/samples/电子商务专业布点数量.xlsx"


def _seed_ref(
    session,
    *,
    ref_id: str = "ref-md",
    version_id: str = "ver-md",
    domain_profile: str = "major_distribution.v1",
    object_uri: str = "s3://bucket/normalized/ref-md.json",
) -> models.NormalizedAssetRef:
    ds = models.DataSource(
        id=f"ds-{ref_id}", code=f"ds-{ref_id}", name="major-dist",
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
        object_uri=f"s3://bucket/raw/{ref_id}.xlsx",
        checksum=f"cs-{ref_id}", mime_type="application/xlsx",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id=f"asset-{ref_id}", data_source_id=ds.id,
        source_object_key=f"{ref_id}.xlsx",
        title="major distribution", asset_kind=AssetKind.RECORD,
        status=AssetVersionStatus.PROCESSING,
    )
    version = models.AssetVersion(
        id=version_id, asset_id=asset.id, raw_object_id=raw.id,
        version_no=1, source_checksum=raw.checksum,
        version_status=AssetVersionStatus.PROCESSING,
    )
    ref = models.NormalizedAssetRef(
        id=ref_id, version_id=version.id,
        normalized_type=NormalizedType.RECORD,
        object_uri=object_uri,
        schema_version="normalized-record.v2",
        checksum=f"cs-ref-{ref_id}",
        status=NormalizedAssetRefStatus.GENERATED,
        governance={}, quality={}, lineage={},
        metadata_summary={"domain_profile": domain_profile},
    )
    session.add_all([ds, batch, raw, asset, version, ref])
    session.commit()
    return ref


def _sample_record_body(path: Path) -> dict:
    wb = parse_xlsx(path.read_bytes(), source_filename=path.name)
    profile = detect(wb).model_dump(mode="json", exclude_none=True)
    return project_to_record_body(wb.model_dump(mode="json"), profile)


@pytest.mark.skipif(not SAMPLE_MAJOR_MULTI.exists(), reason="sample missing")
def test_write_multi_major_sample(session) -> None:
    ref = _seed_ref(session)
    body = _sample_record_body(SAMPLE_MAJOR_MULTI)

    result = write(session=session, normalized_ref=ref, record_body=body)
    session.commit()

    assert result.skipped is False
    dataset = session.get(models.MajorDistributionDataset, result.dataset_id)
    assert dataset is not None
    assert dataset.record_count == 2
    assert dataset.placeholder_count == 1
    assert dataset.ignored_summary_count == 0
    assert dataset.major_scope == "multi_major"
    assert dataset.education_level == "高职"
    records = list(session.scalars(select(models.MajorDistributionRecord)).all())
    assert [r.major_code for r in records] == ["530704", "530702"]
    assert {r.distribution_count for r in records} == {3, 4}


@pytest.mark.skipif(not SAMPLE_MAJOR_ECOMMERCE.exists(), reason="sample missing")
def test_write_ecommerce_sample_ignores_summary(session) -> None:
    ref = _seed_ref(session)
    body = _sample_record_body(SAMPLE_MAJOR_ECOMMERCE)

    result = write(session=session, normalized_ref=ref, record_body=body)
    session.commit()

    dataset = session.get(models.MajorDistributionDataset, result.dataset_id)
    assert dataset is not None
    assert dataset.record_count == 32
    assert dataset.ignored_summary_count == 1
    assert dataset.major_scope == "single_major"
    assert dataset.major_name == "电子商务"
    assert dataset.major_code == "530701"
    assert dataset.education_level is None
    assert dataset.province_count == 31
    assert dataset.quality_summary["ignored_summary_count"] == 1
    records = list(
        session.scalars(
            select(models.MajorDistributionRecord).order_by(
                models.MajorDistributionRecord.source_record_key
            )
        ).all()
    )
    assert len(records) == 32
    assert all(r.province_name != "全部" for r in records)
    assert any(r.province_name == "新疆生产建设兵团" and r.region_scope == "province" for r in records)


@pytest.mark.skipif(not SAMPLE_MAJOR_ECOMMERCE.exists(), reason="sample missing")
def test_dispatch_domain_normalize_major_distribution(session) -> None:
    ref = _seed_ref(session, object_uri="s3://bucket/normalized/ref-md.json")
    body = _sample_record_body(SAMPLE_MAJOR_ECOMMERCE)
    storage = InMemoryObjectStorage()
    storage.put_bytes(
        "normalized/ref-md.json",
        json.dumps({"record_body": body}, ensure_ascii=False).encode("utf-8"),
        content_type="application/json",
    )

    result = dispatch_domain_normalize(session, ref, storage=storage)
    session.commit()

    assert result.skipped is False
    assert result.major_distribution_dataset_id == result.dataset_id
    assert result.records_written == 32
    assert session.scalar(select(models.MajorDistributionDataset)) is not None


@pytest.mark.skipif(not SAMPLE_MAJOR_MULTI.exists(), reason="sample missing")
def test_write_is_idempotent_for_same_ref(session) -> None:
    ref = _seed_ref(session)
    body = _sample_record_body(SAMPLE_MAJOR_MULTI)

    first = write(session=session, normalized_ref=ref, record_body=body)
    session.commit()
    second = write(session=session, normalized_ref=ref, record_body=body)
    session.commit()

    assert first.dataset_id != second.dataset_id
    assert len(list(session.scalars(select(models.MajorDistributionDataset)).all())) == 1
    assert len(list(session.scalars(select(models.MajorDistributionRecord)).all())) == 2
