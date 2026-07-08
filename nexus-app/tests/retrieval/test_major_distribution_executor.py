from __future__ import annotations

import pytest

from nexus_app import models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
)
from nexus_app.retrieval.executors.major_distribution import (
    MajorDistributionRetrievalExecutor,
)
from nexus_app.retrieval.schemas import (
    QueryMetric,
    QueryOrder,
    RetrievalSubQuery,
    StepStatus,
    StructuredPlan,
)
from nexus_app.retrieval.sql_guardrails import StructuredPlanGuardrailError


def _seed_major_distribution(session) -> None:
    ds = models.DataSource(
        id="ds-md",
        code="ds-md",
        name="major distribution",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="batch-md",
        data_source_id=ds.id,
        idempotency_key="idem-md",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="raw-md",
        batch_id=batch.id,
        data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://bucket/raw/md.xlsx",
        checksum="raw-md",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id="asset-md",
        data_source_id=ds.id,
        source_object_key="md.xlsx",
        title="专业布点",
        asset_kind=AssetKind.RECORD,
        status=AssetVersionStatus.AVAILABLE,
    )
    version = models.AssetVersion(
        id="version-md",
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum=raw.checksum,
        version_status=AssetVersionStatus.AVAILABLE,
    )
    ref = models.NormalizedAssetRef(
        id="ref-md",
        version_id=version.id,
        normalized_type=NormalizedType.RECORD,
        object_uri="s3://bucket/normalized/ref-md.json",
        schema_version="normalized-record.v2",
        checksum="ref-md",
        status=NormalizedAssetRefStatus.GENERATED,
        source_type="file_upload",
        content_type="table_sheet",
        title="专业布点",
        language="zh-CN",
        governance={},
        quality={},
        lineage={},
        metadata_summary={"domain_profile": "major_distribution.v1"},
    )
    dataset = models.MajorDistributionDataset(
        id="dataset-md",
        normalized_ref_id=ref.id,
        asset_version_id=version.id,
        dataset_name="电子商务专业布点",
        source_channel="xlsx",
        major_scope="single_major",
        major_name="电子商务",
        major_code="530701",
        education_level="高职",
        year_min=2024,
        year_max=2026,
        province_count=2,
        record_count=4,
        schema_version="major_distribution.v1",
        quality_summary={},
    )
    records = [
        models.MajorDistributionRecord(
            id="record-2024-zj",
            dataset_id=dataset.id,
            normalized_ref_id=ref.id,
            source_record_key="2024-zj",
            source_row_no="2",
            year=2024,
            year_text="2024",
            province_name="浙江",
            region_scope="province",
            major_name="电子商务",
            major_code="530701",
            education_level="高职",
            distribution_count=3,
            quality_flags={},
            trace={},
        ),
        models.MajorDistributionRecord(
            id="record-2025-zj",
            dataset_id=dataset.id,
            normalized_ref_id=ref.id,
            source_record_key="2025-zj",
            source_row_no="3",
            year=2025,
            year_text="2025",
            province_name="浙江",
            region_scope="province",
            major_name="电子商务",
            major_code="530701",
            education_level="高职",
            distribution_count=5,
            quality_flags={},
            trace={},
        ),
        models.MajorDistributionRecord(
            id="record-2026-zj",
            dataset_id=dataset.id,
            normalized_ref_id=ref.id,
            source_record_key="2026-zj",
            source_row_no="4",
            year=2026,
            year_text="2026",
            province_name="浙江",
            region_scope="province",
            major_name="电子商务",
            major_code="530701",
            education_level="高职",
            distribution_count=7,
            quality_flags={},
            trace={},
        ),
        models.MajorDistributionRecord(
            id="record-2026-js",
            dataset_id=dataset.id,
            normalized_ref_id=ref.id,
            source_record_key="2026-js",
            source_row_no="5",
            year=2026,
            year_text="2026",
            province_name="江苏",
            region_scope="province",
            major_name="电子商务",
            major_code="530701",
            education_level="高职",
            distribution_count=9,
            quality_flags={},
            trace={},
        ),
    ]
    session.add_all([ds, batch, raw, asset, version, ref, dataset, *records])
    session.commit()


def _structured_sub_query(plan: StructuredPlan) -> RetrievalSubQuery:
    return RetrievalSubQuery.model_validate(
        {
            "query_id": "q1",
            "channel": "structured",
            "domain": "major_distribution",
            "purpose": "trend_aggregation",
            "query_text": "近三年高职电子商务专业布点数变化",
            "structured_plan": plan.model_dump(),
        }
    )


def test_major_distribution_executor_returns_year_aggregation(session):
    _seed_major_distribution(session)
    executor = MajorDistributionRetrievalExecutor()
    sub_query = _structured_sub_query(
        StructuredPlan(
            table_profile="major_distribution.v1",
            query_profile="major_distribution.trend_by_year",
            filters={"major_name": "电子商务", "education_level": "高职"},
            group_by=["year"],
            metrics=[QueryMetric(field="distribution_count", function="sum")],
            order_by=[QueryOrder(field="year", direction="asc")],
        )
    )

    result = executor.execute(session, sub_query)

    assert result.status == StepStatus.COMPLETED
    assert result.channel == "structured"
    assert result.domain == "major_distribution"
    assert result.result_shape == "aggregation"
    assert result.aggregations[0].group_by == ["year"]
    assert result.aggregations[0].metric == "sum(distribution_count)"
    assert result.aggregations[0].series == [
        {"year": 2024, "value": 3, "record_count": 1},
        {"year": 2025, "value": 5, "record_count": 1},
        {"year": 2026, "value": 16, "record_count": 2},
    ]
    assert len(result.source_refs) == 4
    assert result.source_refs[0].asset_id == "asset-md"
    assert result.source_refs[0].asset_version_id == "version-md"


def test_major_distribution_executor_returns_record_list_with_source_refs(session):
    _seed_major_distribution(session)
    executor = MajorDistributionRetrievalExecutor()
    sub_query = _structured_sub_query(
        StructuredPlan(
            table_profile="major_distribution.v1",
            query_profile="major_distribution.record_list",
            filters={"province_name": "浙江"},
            order_by=[QueryOrder(field="year", direction="asc")],
            limit=10,
        )
    )

    result = executor.execute(session, sub_query)

    assert result.result_shape == "record_list"
    assert [record["year"] for record in result.records] == [2024, 2025, 2026]
    assert result.records[0]["province_name"] == "浙江"
    assert result.source_refs[0].record_ref == "major_distribution_record:record-2024-zj"
    assert result.source_refs[0].locator == {"source_row_no": "2", "row_range": [2, 2]}
    assert result.source_refs[0].metadata["dataset_id"] == "dataset-md"


def test_major_distribution_executor_rejects_unknown_field(session):
    _seed_major_distribution(session)
    executor = MajorDistributionRetrievalExecutor()
    sub_query = _structured_sub_query(
        StructuredPlan(
            table_profile="major_distribution.v1",
            query_profile="major_distribution.record_list",
            filters={"major_name": "电子商务"},
        )
    )
    sub_query.structured_plan.filters["school_name"] = "某学校"

    with pytest.raises(StructuredPlanGuardrailError):
        executor.execute(session, sub_query)


def test_major_distribution_executor_rejects_wrong_domain(session):
    executor = MajorDistributionRetrievalExecutor()
    sub_query = RetrievalSubQuery.model_validate(
        {
            "query_id": "q1",
            "channel": "structured",
            "domain": "job_demand",
            "purpose": "record_list",
            "query_text": "岗位需求",
            "structured_plan": {"table_profile": "job_demand.v1"},
        }
    )

    with pytest.raises(ValueError, match="major_distribution"):
        executor.execute(session, sub_query)

