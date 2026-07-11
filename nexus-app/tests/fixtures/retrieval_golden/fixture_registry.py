"""Named seed functions consumed by :class:`GoldenQuery.fixture_setup`.

Each function seeds the caller's session with the minimal state needed
to run the associated golden query, then returns a small dict of the
IDs the golden expectations reference (so the JSONL can stay stable
even if UUIDs drift).  The harness in
``tests/retrieval/test_golden_baseline.py`` dispatches on the string
key.
"""

from __future__ import annotations

from typing import Any, Callable

from nexus_app import models
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
# Helpers
# ---------------------------------------------------------------------------


def _seed_asset_scaffold(
    session,
    *,
    ref_id: str,
    asset_kind: AssetKind,
    normalized_type: NormalizedType,
    domain_profile: str,
) -> dict[str, str]:
    """Ingest → asset → version → normalized_asset_ref chain."""
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
    return {"version_id": version.id, "ref_id": ref.id}


def _seed_tag(
    session, *,
    target_type: TagAssetIndexTargetType,
    target_id: str,
    asset_version_id: str,
    tag_type: str,
    tag_value: str,
) -> None:
    session.add(models.TagAssetIndex(
        tag_type=tag_type,
        tag_value=tag_value,
        tag_value_normalized=tag_value,
        target_type=target_type,
        target_id=target_id,
        asset_version_id=asset_version_id,
        source=TagAssetIndexSource.FIELD_PROJECTION,
        tag_embedding=None,
    ))


# ---------------------------------------------------------------------------
# Named fixtures
# ---------------------------------------------------------------------------


def seed_major_distribution_zj_js(session) -> dict[str, Any]:
    """浙江 + 江苏 records for 2024 course 电子商务."""
    scaffold = _seed_asset_scaffold(
        session, ref_id="ref-md-zjjs",
        asset_kind=AssetKind.RECORD,
        normalized_type=NormalizedType.RECORD,
        domain_profile="major_distribution.v1",
    )
    dataset = models.MajorDistributionDataset(
        id="ds-md-zjjs", normalized_ref_id=scaffold["ref_id"],
        asset_version_id=scaffold["version_id"],
        dataset_name="fixture", source_channel="xlsx",
        major_scope="single_major", major_name="电子商务",
        major_code="530701", education_level="高职",
        year_min=2024, year_max=2024,
        province_count=2, record_count=2,
        schema_version="major_distribution.v1", quality_summary={},
    )
    record_zj = models.MajorDistributionRecord(
        id="record-zj-2024", dataset_id=dataset.id,
        normalized_ref_id=scaffold["ref_id"],
        source_record_key="2024-zj", source_row_no="2",
        year=2024, year_text="2024",
        province_name="浙江", region_scope="province",
        major_name="电子商务", major_code="530701",
        education_level="高职", distribution_count=3,
        quality_flags={}, trace={},
    )
    record_js = models.MajorDistributionRecord(
        id="record-js-2024", dataset_id=dataset.id,
        normalized_ref_id=scaffold["ref_id"],
        source_record_key="2024-js", source_row_no="3",
        year=2024, year_text="2024",
        province_name="江苏", region_scope="province",
        major_name="电子商务", major_code="530701",
        education_level="高职", distribution_count=5,
        quality_flags={}, trace={},
    )
    session.add_all([dataset, record_zj, record_js])
    session.commit()
    return {
        "asset_version_id": scaffold["version_id"],
        "ref_id": scaffold["ref_id"],
        "record_zj": record_zj.id,
        "record_js": record_js.id,
    }


def seed_major_distribution_with_region_tags(session) -> dict[str, Any]:
    """浙江 record carries a region tag row on tag_asset_index."""
    seeded = seed_major_distribution_zj_js(session)
    _seed_tag(
        session,
        target_type=TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
        target_id=seeded["record_zj"],
        asset_version_id=seeded["asset_version_id"],
        tag_type="region", tag_value="浙江",
    )
    session.commit()
    return seeded


def seed_job_demand_bj_sh(session) -> dict[str, Any]:
    """北京 + 上海 job_demand records + 2 requirement items."""
    scaffold = _seed_asset_scaffold(
        session, ref_id="ref-jd-bjsh",
        asset_kind=AssetKind.RECORD,
        normalized_type=NormalizedType.RECORD,
        domain_profile="job_demand.v1",
    )
    dataset = models.JobDemandDataset(
        id="ds-jd-bjsh", normalized_ref_id=scaffold["ref_id"],
        asset_version_id=scaffold["version_id"],
        source_channel="excel_upload",
        major_name="电子商务", industry_name="直播电商", record_count=2,
        schema_version="job_demand.v1", quality_summary={},
    )
    record_bj = models.JobDemandRecord(
        id="record-jd-bj", dataset_id=dataset.id,
        normalized_ref_id=scaffold["ref_id"],
        source_record_key="k-bj", job_title="电商运营",
        city="北京市", region="华北", education_requirement="本科",
        industry_name="直播电商", record_fingerprint="fp-bj",
        quality_flags={}, trace={},
    )
    record_sh = models.JobDemandRecord(
        id="record-jd-sh", dataset_id=dataset.id,
        normalized_ref_id=scaffold["ref_id"],
        source_record_key="k-sh", job_title="用户增长",
        city="上海市", region="华东", education_requirement="本科",
        industry_name="直播电商", record_fingerprint="fp-sh",
        quality_flags={}, trace={},
    )
    item_bj = models.JobDemandRequirementItem(
        id="item-jd-bj", record_id=record_bj.id,
        dataset_id=dataset.id, item_type="professional_skill",
        item_name="直播运营", raw_text="",
        normalized_name="直播运营",
        confidence=0.9, evidence_field="requirement_text",
    )
    item_sh = models.JobDemandRequirementItem(
        id="item-jd-sh", record_id=record_sh.id,
        dataset_id=dataset.id, item_type="professional_skill",
        item_name="用户增长", raw_text="",
        normalized_name="用户增长",
        confidence=0.9, evidence_field="requirement_text",
    )
    session.add_all([dataset, record_bj, record_sh, item_bj, item_sh])
    session.commit()
    return {
        "asset_version_id": scaffold["version_id"],
        "ref_id": scaffold["ref_id"],
        "record_bj": record_bj.id,
        "record_sh": record_sh.id,
        "item_bj": item_bj.id,
        "item_sh": item_sh.id,
    }


def seed_job_demand_with_region_tags(session) -> dict[str, Any]:
    seeded = seed_job_demand_bj_sh(session)
    _seed_tag(
        session,
        target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
        target_id=seeded["record_bj"],
        asset_version_id=seeded["asset_version_id"],
        tag_type="region", tag_value="北京",
    )
    session.commit()
    return seeded


def seed_job_demand_weighted_rerank(session) -> dict[str, Any]:
    """BJ hits regions + industries; SH hits only regions."""
    seeded = seed_job_demand_bj_sh(session)
    _seed_tag(
        session,
        target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
        target_id=seeded["record_bj"],
        asset_version_id=seeded["asset_version_id"],
        tag_type="region", tag_value="北京",
    )
    _seed_tag(
        session,
        target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
        target_id=seeded["record_bj"],
        asset_version_id=seeded["asset_version_id"],
        tag_type="industry", tag_value="直播电商",
    )
    _seed_tag(
        session,
        target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
        target_id=seeded["record_sh"],
        asset_version_id=seeded["asset_version_id"],
        tag_type="region", tag_value="上海",
    )
    session.commit()
    return seeded


FIXTURE_REGISTRY: dict[str, Callable] = {
    "major_distribution_zj_js": seed_major_distribution_zj_js,
    "major_distribution_with_region_tags": seed_major_distribution_with_region_tags,
    "job_demand_bj_sh": seed_job_demand_bj_sh,
    "job_demand_with_region_tags": seed_job_demand_with_region_tags,
    "job_demand_weighted_rerank": seed_job_demand_weighted_rerank,
}


def seed_fixture(name: str, session) -> dict[str, Any]:
    if name not in FIXTURE_REGISTRY:
        raise KeyError(
            f"unknown golden fixture {name!r}; registered: "
            f"{sorted(FIXTURE_REGISTRY)}"
        )
    return FIXTURE_REGISTRY[name](session)
