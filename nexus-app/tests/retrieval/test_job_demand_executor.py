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
from nexus_app.retrieval.executors.job_demand import JobDemandRetrievalExecutor
from nexus_app.retrieval.schemas import QueryMetric, QueryOrder, RetrievalSubQuery, StructuredPlan
from nexus_app.retrieval.sql_guardrails import StructuredPlanGuardrailError


def _seed_job_demand(session) -> None:
    ds = models.DataSource(
        id="ds-jd",
        code="ds-jd",
        name="job demand",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="batch-jd",
        data_source_id=ds.id,
        idempotency_key="idem-jd",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="raw-jd",
        batch_id=batch.id,
        data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://bucket/raw/jd.xlsx",
        checksum="raw-jd",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id="asset-jd",
        data_source_id=ds.id,
        source_object_key="jd.xlsx",
        title="岗位需求",
        asset_kind=AssetKind.RECORD,
        status=AssetVersionStatus.AVAILABLE,
    )
    version = models.AssetVersion(
        id="version-jd",
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum=raw.checksum,
        version_status=AssetVersionStatus.AVAILABLE,
    )
    ref = models.NormalizedAssetRef(
        id="ref-jd",
        version_id=version.id,
        normalized_type=NormalizedType.RECORD,
        object_uri="s3://bucket/normalized/ref-jd.json",
        schema_version="normalized-record.v2",
        checksum="ref-jd",
        status=NormalizedAssetRefStatus.GENERATED,
        source_type="file_upload",
        content_type="table_sheet",
        title="岗位需求",
        language="zh-CN",
        governance={},
        quality={},
        lineage={},
        metadata_summary={"domain_profile": "job_demand.v1"},
    )
    dataset = models.JobDemandDataset(
        id="dataset-jd",
        normalized_ref_id=ref.id,
        asset_version_id=version.id,
        major_name="电子商务",
        industry_name="互联网",
        source_channel="excel_upload",
        record_count=3,
        schema_version="job_demand.v1",
        quality_summary={},
    )
    records = [
        models.JobDemandRecord(
            id="record-jd-sh",
            dataset_id=dataset.id,
            normalized_ref_id=ref.id,
            source_record_key="Sheet1#2",
            job_title="电商运营",
            employment_type="全职",
            job_count=2,
            city="上海",
            salary_min=8.0,
            salary_max=12.0,
            education_requirement="大专",
            company_name="ACME",
            industry_name="互联网",
            job_skill_text="直播运营 数据分析",
            requirement_text="熟悉直播平台",
            record_fingerprint="fp-sh",
            quality_flags={},
            trace={"sheet": "Sheet1", "row": 2},
        ),
        models.JobDemandRecord(
            id="record-jd-hz",
            dataset_id=dataset.id,
            normalized_ref_id=ref.id,
            source_record_key="Sheet1#3",
            job_title="数据分析师",
            employment_type="全职",
            job_count=1,
            city="杭州",
            salary_min=10.0,
            salary_max=15.0,
            education_requirement="本科",
            company_name="Beta",
            industry_name="互联网",
            job_skill_text="SQL Python",
            requirement_text="熟悉数据分析",
            record_fingerprint="fp-hz",
            quality_flags={},
            trace={"sheet": "Sheet1", "row": 3},
        ),
    ]
    requirement = models.JobDemandRequirementItem(
        id="req-jd-1",
        record_id="record-jd-sh",
        dataset_id=dataset.id,
        item_type="professional_skill",
        item_name="直播运营",
        raw_text="熟悉直播平台",
        normalized_name="直播运营",
        confidence=0.9,
        evidence_field="requirement_text",
    )
    session.add_all([ds, batch, raw, asset, version, ref, dataset, *records, requirement])
    session.commit()


def _sub_query(plan: StructuredPlan) -> RetrievalSubQuery:
    return RetrievalSubQuery.model_validate(
        {
            "query_id": "q1",
            "channel": "structured",
            "domain": "job_demand",
            "purpose": "job_demand_query",
            "query_text": "电子商务岗位需求",
            "structured_plan": plan.model_dump(),
        }
    )


def test_job_demand_executor_returns_city_aggregation(session):
    _seed_job_demand(session)
    result = JobDemandRetrievalExecutor().execute(
        session,
        _sub_query(
            StructuredPlan(
                table_profile="job_demand.v1",
                query_profile="job_demand.count_by_city",
                filters={"industry_name": "互联网"},
                group_by=["city"],
                metrics=[QueryMetric(field="job_count", function="sum")],
                order_by=[QueryOrder(field="city", direction="asc")],
            )
        ),
    )

    assert result.result_shape == "aggregation"
    assert result.aggregations[0].group_by == ["city"]
    assert result.aggregations[0].metric == "sum(job_count)"
    assert result.aggregations[0].series == [
        {"city": "上海", "value": 2, "record_count": 1},
        {"city": "杭州", "value": 1, "record_count": 1},
    ]
    assert result.source_refs[0].asset_id == "asset-jd"


def test_job_demand_executor_returns_record_list_with_source_refs(session):
    _seed_job_demand(session)
    result = JobDemandRetrievalExecutor().execute(
        session,
        _sub_query(
            StructuredPlan(
                table_profile="job_demand.v1",
                query_profile="job_demand.record_list",
                filters={"city": "上海"},
                order_by=[QueryOrder(field="job_title", direction="asc")],
            )
        ),
    )

    assert result.result_shape == "record_list"
    assert result.records[0]["job_title"] == "电商运营"
    assert result.source_refs[0].record_ref == "job_demand_record:record-jd-sh"
    assert result.source_refs[0].locator == {"sheet": "Sheet1", "row": 2, "row_range": [2, 2]}


def test_job_demand_executor_returns_requirement_items(session):
    _seed_job_demand(session)
    result = JobDemandRetrievalExecutor().execute(
        session,
        _sub_query(
            StructuredPlan(
                table_profile="job_demand.v1",
                query_profile="job_demand.requirement_keyword",
                filters={"item_name": "直播"},
            )
        ),
    )

    assert result.result_shape == "requirement_items"
    assert result.records[0]["item_name"] == "直播运营"
    assert result.records[0]["job_record"]["job_title"] == "电商运营"
    assert result.source_refs[0].record_ref == "job_demand_requirement_item:req-jd-1"
    assert result.source_refs[0].metadata["requirement_item_id"] == "req-jd-1"


def test_job_demand_executor_rejects_non_whitelisted_filter(session):
    _seed_job_demand(session)
    plan = StructuredPlan(
        table_profile="job_demand.v1",
        query_profile="job_demand.record_list",
        filters={"school_name": "某学校"},
    )

    with pytest.raises(StructuredPlanGuardrailError):
        JobDemandRetrievalExecutor().execute(session, _sub_query(plan))
