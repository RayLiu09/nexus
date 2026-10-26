"""Document tag combinations and current structured retrieval boundaries.

Tag Phase A uses document references. Structured domains use field filters
and reject retired tag buckets before querying SQL. The low-level target-ID
helper remains covered independently of executor admission rules.
"""

from __future__ import annotations

from typing import Any

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
from nexus_app.retrieval.domain_registry import get_query_profile
from nexus_app.retrieval.executors.job_demand import JobDemandRetrievalExecutor
from nexus_app.retrieval.executors.major_distribution import (
    MajorDistributionRetrievalExecutor,
)
from nexus_app.retrieval.schemas import RetrievalSubQuery, StepStatus
from nexus_app.retrieval.sql_guardrails import StructuredPlanGuardrailError
from nexus_app.retrieval.sql_guardrails import TARGET_ID_IN_KEY
from nexus_app.retrieval.tag_filter_execution import (
    apply_target_id_in_to_filters,
    execute_tag_filters,
)
from nexus_app.retrieval.tag_resolver import TagAssetIndexResolver
from nexus_app.retrieval.tag_schemas import TagFilter

from tests.fixtures.retrieval_documents import seed_documents, add_tag, document_query


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_job_demand_min(session) -> dict[str, str]:
    ds = models.DataSource(
        id="ds-jd", code="ds-jd", name="jd",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="batch-jd", data_source_id=ds.id, idempotency_key="idem-jd",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="raw-jd", batch_id=batch.id, data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://x/jd.xlsx", checksum="raw-jd",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id="asset-jd", data_source_id=ds.id, source_object_key="jd.xlsx",
        title="jd", asset_kind=AssetKind.RECORD,
        status=AssetVersionStatus.AVAILABLE,
    )
    version = models.AssetVersion(
        id="version-jd", asset_id=asset.id, raw_object_id=raw.id,
        version_no=1, source_checksum=raw.checksum,
        version_status=AssetVersionStatus.AVAILABLE,
    )
    ref = models.NormalizedAssetRef(
        id="ref-jd", version_id=version.id,
        normalized_type=NormalizedType.RECORD,
        object_uri="s3://x/jd.json", schema_version="normalized-record.v2",
        checksum="ref-jd", status=NormalizedAssetRefStatus.GENERATED,
        source_type="file_upload", content_type="table_sheet",
        title="jd", language="zh-CN",
        governance={}, quality={}, lineage={},
        metadata_summary={"domain_profile": "job_demand.v1"},
    )
    dataset = models.JobDemandDataset(
        id="dataset-jd", normalized_ref_id=ref.id, asset_version_id=version.id,
        source_channel="excel_upload",
        major_name="电子商务", industry_name="互联网", record_count=2,
        schema_version="job_demand.v1", quality_summary={},
    )
    record_bj = models.JobDemandRecord(
        id="record-bj", dataset_id=dataset.id, normalized_ref_id=ref.id,
        source_record_key="key-bj",
        job_title="电商运营", city="北京市", region="华北",
        education_requirement="本科", employment_type="全职",
        industry_name="直播电商", record_fingerprint="fp-bj",
        quality_flags={}, trace={},
    )
    record_sh = models.JobDemandRecord(
        id="record-sh", dataset_id=dataset.id, normalized_ref_id=ref.id,
        source_record_key="key-sh",
        job_title="电商运营", city="上海市", region="华东",
        education_requirement="本科", employment_type="全职",
        industry_name="直播电商", record_fingerprint="fp-sh",
        quality_flags={}, trace={},
    )
    item_bj = models.JobDemandRequirementItem(
        id="item-bj", record_id=record_bj.id, dataset_id=dataset.id,
        item_type="professional_skill", item_name="直播运营",
        raw_text="熟悉直播运营", normalized_name="直播运营",
        taxonomy_code=None, confidence=0.9, evidence_field="requirement_text",
    )
    item_sh = models.JobDemandRequirementItem(
        id="item-sh", record_id=record_sh.id, dataset_id=dataset.id,
        item_type="professional_skill", item_name="用户增长",
        raw_text="用户增长经验", normalized_name="用户增长",
        taxonomy_code=None, confidence=0.9, evidence_field="requirement_text",
    )
    session.add_all([ds, batch, raw, asset, version, ref, dataset,
                     record_bj, record_sh, item_bj, item_sh])
    session.commit()
    return {
        "version_id": "version-jd",
        "record_bj": "record-bj",
        "record_sh": "record-sh",
        "item_bj": "item-bj",
        "item_sh": "item-sh",
    }


# ---------------------------------------------------------------------------
# Phase A — pure execute_tag_filters
# ---------------------------------------------------------------------------


class TestPhaseAExecution:
    """Tag combinations operate on document refs; structured profiles stay retired."""

    @pytest.mark.parametrize(
        "combine, expected",
        [("AND", {"ref-tags-a"}), ("OR", {"ref-tags-a", "ref-tags-b"})],
    )
    def test_combines_document_buckets(self, session, combine, expected):
        a, b = seed_documents(session)
        add_tag(session, a, "majors", "直播")
        add_tag(session, a, "topics", "运营")
        add_tag(session, b, "topics", "运营")
        query = document_query(
            {"majors": ["直播"], "topics": ["运营"]}, combine=combine
        )
        result = execute_tag_filters(
            sub_query=query,
            profile=get_query_profile("course_textbook", "semantic_chunk"),
            resolver=TagAssetIndexResolver(session),
        )
        assert result.target_ids == expected
        assert result.bucket_hit_counts == {"majors": 1, "topics": 2}
        assert result.match_layer_counts["L1"] == 3

    @pytest.mark.parametrize("optional", [True, False])
    def test_empty_document_bucket(self, session, optional):
        a, b = seed_documents(session)
        add_tag(session, a, "majors", "直播")
        query = document_query({"majors": ["直播"], "topics": ["不存在"]})
        query.tag_filters["topics"].optional = optional
        result = execute_tag_filters(
            sub_query=query,
            profile=get_query_profile("course_textbook", "semantic_chunk"),
            resolver=TagAssetIndexResolver(session),
        )
        assert result.target_ids == ({a} if optional else set())
        assert result.dropped_optional_buckets == (["topics"] if optional else [])
        assert ("tag_filters_empty_intersection" in result.warnings) == (not optional)

    def test_binding_string_deferred(self, session):
        seed_documents(session)
        query = document_query({"majors": "$binding.major_tags"})
        result = execute_tag_filters(
            sub_query=query,
            profile=get_query_profile("course_textbook", "semantic_chunk"),
            resolver=TagAssetIndexResolver(session),
        )
        assert result.target_ids is None
        assert any("binding_deferred" in w for w in result.warnings)

    def test_out_of_domain_document_bucket_is_skipped(self, session):
        query = document_query({"regions": ["北京"]})
        result = execute_tag_filters(
            sub_query=query,
            profile=get_query_profile("course_textbook", "semantic_chunk"),
            resolver=TagAssetIndexResolver(session),
        )
        assert not result.applied
        assert result.skipped_bucket_out_of_domain == ["regions"]
        assert result.warnings == ["tag_filter_bucket_out_of_domain:regions"]

    def test_no_filters_is_noop(self, session):
        result = execute_tag_filters(
            sub_query=document_query(),
            profile=get_query_profile("course_textbook", "semantic_chunk"),
            resolver=TagAssetIndexResolver(session),
        )
        assert not result.applied and result.warnings == []

    def test_unconfigured_structured_target_is_noop_at_helper_boundary(self, session):
        query = RetrievalSubQuery.model_validate(
            {
                "query_id": "q",
                "channel": "structured",
                "domain": "job_demand",
                "purpose": "test",
                "query_text": "岗位",
                "structured_plan": {
                    "table_profile": "job_demand.v1",
                    "query_profile": "job_demand.record_list",
                },
                "tag_filters": {"regions": TagFilter(tags=["北京"]).model_dump()},
            }
        )
        result = execute_tag_filters(
            sub_query=query,
            profile=get_query_profile("job_demand", "job_demand.record_list"),
            resolver=TagAssetIndexResolver(session),
        )
        assert not result.applied
        assert result.warnings == ["tag_target_type_not_configured"]


# ---------------------------------------------------------------------------
# apply_target_id_in_to_filters
# ---------------------------------------------------------------------------


class TestApplyTargetIdInHelper:
    def test_none_target_ids_leaves_filters_untouched(self):
        filters = {"x": 1}
        apply_target_id_in_to_filters(
            filters=filters, target_ids=None, key=TARGET_ID_IN_KEY,
        )
        assert filters == {"x": 1}

    def test_empty_set_writes_empty_list(self):
        filters: dict[str, Any] = {}
        apply_target_id_in_to_filters(
            filters=filters, target_ids=set(), key=TARGET_ID_IN_KEY,
        )
        assert filters[TARGET_ID_IN_KEY] == []

    def test_writes_sorted_list(self):
        filters: dict[str, Any] = {}
        apply_target_id_in_to_filters(
            filters=filters,
            target_ids={"b", "a", "c"},
            key=TARGET_ID_IN_KEY,
        )
        assert filters[TARGET_ID_IN_KEY] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Major offering current read model and retired-tag guardrails
# ---------------------------------------------------------------------------


class TestMajorDistributionTwoPhase:

    def test_current_facts_and_structured_filters(self, session):
        from tests.fixtures.retrieval_golden.fixture_registry import seed_major_distribution_zj_js
        seeded = seed_major_distribution_zj_js(session)
        query = RetrievalSubQuery.model_validate(
            {
                "query_id": "q",
                "channel": "structured",
                "domain": "major_distribution",
                "purpose": "test",
                "query_text": "布点",
                "structured_plan": {
                    "table_profile": "major_offering.v1",
                    "query_profile": "major_distribution.record_list",
                },
            }
        )
        executor = MajorDistributionRetrievalExecutor()
        result = executor.execute(session, query)
        assert {r["id"] for r in result.records} == {
            seeded["record_zj"],
            seeded["record_js"],
        }
        assert "ingested_coverage_only" in result.warnings
        query.structured_filters = {"province_name": "浙江"}
        assert [r["id"] for r in executor.execute(session, query).records] == [
            seeded["record_zj"]
        ]

    @pytest.mark.parametrize(
        "buckets",
        [{"regions": ["浙江"]}, {"regions": ["浙江"], "majors": ["其他专业"]}],
    )
    def test_retired_tags_rejected_before_sql(self, session, monkeypatch, buckets):
        query = RetrievalSubQuery.model_validate(
            {
                "query_id": "q",
                "channel": "structured",
                "domain": "major_distribution",
                "purpose": "test",
                "query_text": "布点",
                "structured_plan": {
                    "table_profile": "major_offering.v1",
                    "query_profile": "major_distribution.record_list",
                },
                "tag_filters": {
                    k: TagFilter(tags=v).model_dump() for k, v in buckets.items()
                },
            }
        )
        monkeypatch.setattr(
            session,
            "scalars",
            lambda *_a, **_k: pytest.fail("retired tags must fail before SQL"),
        )
        with pytest.raises(StructuredPlanGuardrailError, match="not allowed"):
            MajorDistributionRetrievalExecutor().execute(session, query)


# ---------------------------------------------------------------------------
# Job demand field-filter integration
# ---------------------------------------------------------------------------


class TestJobDemandTwoPhase:

    @pytest.mark.parametrize(
        "profile,filters,key",
        [
            ("job_demand.record_list", {"city": "北京市"}, "record_bj"),
            (
                "job_demand.requirement_keyword",
                {"normalized_name": "直播运营"},
                "item_bj",
            ),
        ],
    )
    def test_domain_columns_narrow_records(self, session, profile, filters, key):
        seeded = _seed_job_demand_min(session)
        query = RetrievalSubQuery.model_validate(
            {
                "query_id": "q",
                "channel": "structured",
                "domain": "job_demand",
                "purpose": "test",
                "query_text": "岗位",
                "structured_plan": {
                    "table_profile": "job_demand.v1",
                    "query_profile": profile,
                    "filters": filters,
                },
            }
        )
        result = JobDemandRetrievalExecutor().execute(session, query)
        assert result.status == StepStatus.COMPLETED
        assert [r["id"] for r in result.records] == [seeded[key]]
        assert "tag_filter_target_ids_count" not in result.retrieval_meta

    def test_city_column_narrows_aggregation(self, session):
        _seed_job_demand_min(session)
        query = RetrievalSubQuery.model_validate(
            {
                "query_id": "q",
                "channel": "structured",
                "domain": "job_demand",
                "purpose": "test",
                "query_text": "岗位",
                "structured_plan": {
                    "table_profile": "job_demand.v1",
                    "query_profile": "job_demand.count_by_city",
                    "filters": {"city": "北京市"},
                    "group_by": ["city"],
                    "metrics": [{"field": "record", "function": "count"}],
                },
            }
        )
        result = JobDemandRetrievalExecutor().execute(session, query)
        assert len(result.aggregations[0].series) == 1
        assert result.aggregations[0].series[0]["city"] == "北京市"
        assert result.aggregations[0].series[0]["value"] == 1
