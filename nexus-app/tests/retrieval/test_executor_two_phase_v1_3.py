"""PR-9 guards for the two-phase structured executor.

Phase A: ``tag_filters`` → target_id set via
:class:`TagAssetIndexResolver` (narrowed to profile.tag_target_type).
Phase B: SQL executor injects ``TARGET_ID_IN_KEY`` into
``structured_plan.filters`` and adds ``WHERE anchor.id IN (…)``.

Coverage:

* Phase A unit — combine AND/OR intersect/union, optional-empty
  dropping, binding-string deferral, out-of-domain bucket rejection,
  no-tag_target_type profile fallback.
* Two-phase integration — major_distribution + job_demand +
  requirement_keyword executors run the fold + SQL correctly and short-
  circuit when Phase A intersects to empty.
* Competency fallback — tag_filters attached to a competency sub_query
  emits ``tag_target_type_not_configured`` but doesn't fail the query.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    TagAssetIndexSource,
    TagAssetIndexTargetType,
)
from nexus_app.retrieval.domain_registry import get_query_profile
from nexus_app.retrieval.executors.competency import CompetencyRetrievalExecutor
from nexus_app.retrieval.executors.job_demand import JobDemandRetrievalExecutor
from nexus_app.retrieval.executors.major_distribution import (
    MajorDistributionRetrievalExecutor,
)
from nexus_app.retrieval.schemas import (
    BusinessDomain,
    RetrievalSubQuery,
    StepStatus,
    StructuredPlan,
)
from nexus_app.retrieval.sql_guardrails import TARGET_ID_IN_KEY
from nexus_app.retrieval.tag_filter_execution import (
    TagFilterExecutionResult,
    apply_target_id_in_to_filters,
    execute_tag_filters,
)
from nexus_app.retrieval.tag_resolver import TagAssetIndexResolver
from nexus_app.retrieval.tag_schemas import TagFilter


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_major_distribution_min(session) -> dict[str, str]:
    """Two records: 浙江 (record-zj) + 江苏 (record-js)."""
    ds = models.DataSource(
        id="ds-md", code="ds-md", name="md",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="batch-md", data_source_id=ds.id, idempotency_key="idem-md",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="raw-md", batch_id=batch.id, data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://x/md.xlsx", checksum="raw-md",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id="asset-md", data_source_id=ds.id, source_object_key="md.xlsx",
        title="md", asset_kind=AssetKind.RECORD,
        status=AssetVersionStatus.AVAILABLE,
    )
    version = models.AssetVersion(
        id="version-md", asset_id=asset.id, raw_object_id=raw.id,
        version_no=1, source_checksum=raw.checksum,
        version_status=AssetVersionStatus.AVAILABLE,
    )
    ref = models.NormalizedAssetRef(
        id="ref-md", version_id=version.id,
        normalized_type=NormalizedType.RECORD,
        object_uri="s3://x/md.json", schema_version="normalized-record.v2",
        checksum="ref-md", status=NormalizedAssetRefStatus.GENERATED,
        source_type="file_upload", content_type="table_sheet",
        title="md", language="zh-CN",
        governance={}, quality={}, lineage={},
        metadata_summary={"domain_profile": "major_distribution.v1"},
    )
    dataset = models.MajorDistributionDataset(
        id="dataset-md", normalized_ref_id=ref.id, asset_version_id=version.id,
        dataset_name="md-ds", source_channel="xlsx",
        major_scope="single_major", major_name="电子商务", major_code="530701",
        education_level="高职", year_min=2024, year_max=2026,
        province_count=2, record_count=2,
        schema_version="major_distribution.v1", quality_summary={},
    )
    record_zj = models.MajorDistributionRecord(
        id="record-zj", dataset_id=dataset.id, normalized_ref_id=ref.id,
        source_record_key="2024-zj", source_row_no="2", year=2024,
        year_text="2024", province_name="浙江", region_scope="province",
        major_name="电子商务", major_code="530701", education_level="高职",
        distribution_count=3, quality_flags={}, trace={},
    )
    record_js = models.MajorDistributionRecord(
        id="record-js", dataset_id=dataset.id, normalized_ref_id=ref.id,
        source_record_key="2024-js", source_row_no="3", year=2024,
        year_text="2024", province_name="江苏", region_scope="province",
        major_name="电子商务", major_code="530701", education_level="高职",
        distribution_count=5, quality_flags={}, trace={},
    )
    session.add_all([ds, batch, raw, asset, version, ref, dataset, record_zj, record_js])
    session.commit()
    return {"version_id": "version-md", "record_zj": "record-zj", "record_js": "record-js"}


def _seed_tag_index(
    session,
    *,
    target_type: TagAssetIndexTargetType,
    target_id: str,
    asset_version_id: str,
    tag_type: str,
    tag_value: str,
    tag_value_normalized: str | None = None,
    source: TagAssetIndexSource = TagAssetIndexSource.FIELD_PROJECTION,
) -> None:
    session.add(models.TagAssetIndex(
        tag_type=tag_type,
        tag_value=tag_value,
        tag_value_normalized=tag_value_normalized or tag_value,
        target_type=target_type,
        target_id=target_id,
        asset_version_id=asset_version_id,
        source=source,
        tag_embedding=None,
    ))
    session.commit()


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
    def test_no_tag_filters_is_noop(self, session):
        profile = get_query_profile(
            BusinessDomain.MAJOR_DISTRIBUTION, "major_distribution.record_list",
        )
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1",
            "channel": "structured",
            "domain": "major_distribution",
            "purpose": "test",
            "query_text": "浙江专业布点",
            "structured_plan": {
                "table_profile": "major_distribution.v1",
                "query_profile": "major_distribution.record_list",
                "filters": {},
            },
        })
        result = execute_tag_filters(
            sub_query=sub_query, profile=profile,
            resolver=TagAssetIndexResolver(session),
        )
        assert result.target_ids is None
        assert result.applied is False
        assert result.warnings == []

    def test_and_intersects_two_buckets(self, session):
        seeded = _seed_major_distribution_min(session)
        # regions:浙江 → both records; but we only project it onto record-zj
        _seed_tag_index(
            session,
            target_type=TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
            target_id=seeded["record_zj"],
            asset_version_id=seeded["version_id"],
            tag_type="region", tag_value="浙江", tag_value_normalized="浙江",
        )
        _seed_tag_index(
            session,
            target_type=TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
            target_id=seeded["record_zj"],
            asset_version_id=seeded["version_id"],
            tag_type="major", tag_value="电子商务", tag_value_normalized="电子商务",
        )
        _seed_tag_index(
            session,
            target_type=TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
            target_id=seeded["record_js"],
            asset_version_id=seeded["version_id"],
            tag_type="major", tag_value="电子商务", tag_value_normalized="电子商务",
        )
        # regions ∩ majors intersect → only record-zj
        profile = get_query_profile(
            BusinessDomain.MAJOR_DISTRIBUTION, "major_distribution.record_list",
        )
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured", "domain": "major_distribution",
            "purpose": "test", "query_text": "test",
            "structured_plan": {
                "table_profile": "major_distribution.v1",
                "query_profile": "major_distribution.record_list",
            },
            "tag_filters": {
                "regions": TagFilter(tags=["浙江"], match_strategy="l1|l1.5").model_dump(),
                "majors": TagFilter(tags=["电子商务"], match_strategy="l1|l1.5").model_dump(),
            },
        })
        result = execute_tag_filters(
            sub_query=sub_query, profile=profile,
            resolver=TagAssetIndexResolver(session),
        )
        assert result.applied
        assert result.target_ids == {seeded["record_zj"]}
        assert result.bucket_hit_counts == {"regions": 1, "majors": 2}
        assert result.match_layer_counts.get("L1", 0) >= 3  # 3 hits total

    def test_or_unions_two_buckets(self, session):
        seeded = _seed_major_distribution_min(session)
        _seed_tag_index(
            session,
            target_type=TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
            target_id=seeded["record_zj"],
            asset_version_id=seeded["version_id"],
            tag_type="region", tag_value="浙江", tag_value_normalized="浙江",
        )
        _seed_tag_index(
            session,
            target_type=TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
            target_id=seeded["record_js"],
            asset_version_id=seeded["version_id"],
            tag_type="region", tag_value="江苏", tag_value_normalized="江苏",
        )
        profile = get_query_profile(
            BusinessDomain.MAJOR_DISTRIBUTION, "major_distribution.record_list",
        )
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured", "domain": "major_distribution",
            "purpose": "test", "query_text": "test",
            "structured_plan": {
                "table_profile": "major_distribution.v1",
                "query_profile": "major_distribution.record_list",
            },
            "tag_filters": {
                "regions": TagFilter(
                    tags=["浙江", "江苏"], match_strategy="l1|l1.5",
                ).model_dump(),
            },
            "combine": "OR",
        })
        result = execute_tag_filters(
            sub_query=sub_query, profile=profile,
            resolver=TagAssetIndexResolver(session),
        )
        assert result.target_ids == {seeded["record_zj"], seeded["record_js"]}

    def test_optional_empty_bucket_dropped_from_and(self, session):
        seeded = _seed_major_distribution_min(session)
        _seed_tag_index(
            session,
            target_type=TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
            target_id=seeded["record_zj"],
            asset_version_id=seeded["version_id"],
            tag_type="region", tag_value="浙江", tag_value_normalized="浙江",
        )
        profile = get_query_profile(
            BusinessDomain.MAJOR_DISTRIBUTION, "major_distribution.record_list",
        )
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured", "domain": "major_distribution",
            "purpose": "test", "query_text": "test",
            "structured_plan": {
                "table_profile": "major_distribution.v1",
                "query_profile": "major_distribution.record_list",
            },
            "tag_filters": {
                "regions": TagFilter(
                    tags=["浙江"], match_strategy="l1|l1.5",
                ).model_dump(),
                "majors": TagFilter(
                    tags=["不存在的专业"], match_strategy="l1|l1.5", optional=True,
                ).model_dump(),
            },
        })
        result = execute_tag_filters(
            sub_query=sub_query, profile=profile,
            resolver=TagAssetIndexResolver(session),
        )
        # optional-empty bucket dropped; regions alone contributes record-zj
        assert result.target_ids == {seeded["record_zj"]}
        assert "majors" in result.dropped_optional_buckets

    def test_mandatory_empty_bucket_collapses_and(self, session):
        seeded = _seed_major_distribution_min(session)
        _seed_tag_index(
            session,
            target_type=TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
            target_id=seeded["record_zj"],
            asset_version_id=seeded["version_id"],
            tag_type="region", tag_value="浙江", tag_value_normalized="浙江",
        )
        profile = get_query_profile(
            BusinessDomain.MAJOR_DISTRIBUTION, "major_distribution.record_list",
        )
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured", "domain": "major_distribution",
            "purpose": "test", "query_text": "test",
            "structured_plan": {
                "table_profile": "major_distribution.v1",
                "query_profile": "major_distribution.record_list",
            },
            "tag_filters": {
                "regions": TagFilter(
                    tags=["浙江"], match_strategy="l1|l1.5",
                ).model_dump(),
                "majors": TagFilter(
                    tags=["不存在"], match_strategy="l1|l1.5",  # NOT optional
                ).model_dump(),
            },
        })
        result = execute_tag_filters(
            sub_query=sub_query, profile=profile,
            resolver=TagAssetIndexResolver(session),
        )
        assert result.applied
        assert result.target_ids == set()  # empty intersection
        assert "tag_filters_empty_intersection" in result.warnings

    def test_binding_string_deferred(self, session):
        profile = get_query_profile(
            BusinessDomain.MAJOR_DISTRIBUTION, "major_distribution.record_list",
        )
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured", "domain": "major_distribution",
            "purpose": "test", "query_text": "test",
            "structured_plan": {
                "table_profile": "major_distribution.v1",
                "query_profile": "major_distribution.record_list",
            },
            "tag_filters": {
                "regions": TagFilter(
                    tags="$q_job.output.records[*].region",
                    match_strategy="l1|l1.5",
                ).model_dump(),
            },
        })
        result = execute_tag_filters(
            sub_query=sub_query, profile=profile,
            resolver=TagAssetIndexResolver(session),
        )
        assert any(
            w.startswith("tag_filter_binding_deferred_to_dag")
            for w in result.warnings
        )

    def test_profile_without_target_type_emits_warning(self, session):
        # PR-13b — competency.task_tree / ability_items_* now expose
        # OCCUPATIONAL_ABILITY_ITEM anchor.  ``relations_by_ability``
        # is the last competency profile that still declines tag_filters
        # (polymorphic relation.target_id, PR-13b.2 deferred).
        profile = get_query_profile(
            BusinessDomain.COMPETENCY_ANALYSIS, "competency.relations_by_ability",
        )
        assert profile.tag_target_type is None
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured", "domain": "competency_analysis",
            "purpose": "test", "query_text": "test",
            "structured_plan": {
                "table_profile": "ability_analysis.pgsd.v1",
                "query_profile": "competency.relations_by_ability",
            },
            "tag_filters": {
                "abilities": TagFilter(tags=["Python"]).model_dump(),
            },
        })
        result = execute_tag_filters(
            sub_query=sub_query, profile=profile,
            resolver=TagAssetIndexResolver(session),
        )
        assert result.applied is False
        assert "tag_target_type_not_configured" in result.warnings


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
# MajorDistributionRetrievalExecutor two-phase integration
# ---------------------------------------------------------------------------


class TestMajorDistributionTwoPhase:
    def test_no_tag_filter_behaves_as_pre_v1_3(self, session):
        seeded = _seed_major_distribution_min(session)
        executor = MajorDistributionRetrievalExecutor()
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured",
            "domain": "major_distribution", "purpose": "test",
            "query_text": "test",
            "structured_plan": {
                "table_profile": "major_distribution.v1",
                "query_profile": "major_distribution.record_list",
            },
        })
        result = executor.execute(session, sub_query)
        assert result.status == StepStatus.COMPLETED
        assert {r["id"] for r in result.records} == {
            seeded["record_zj"], seeded["record_js"]
        }
        assert result.warnings == []

    def test_tag_filter_narrows_to_resolved_ids(self, session):
        seeded = _seed_major_distribution_min(session)
        _seed_tag_index(
            session,
            target_type=TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
            target_id=seeded["record_zj"],
            asset_version_id=seeded["version_id"],
            tag_type="region", tag_value="浙江", tag_value_normalized="浙江",
        )
        executor = MajorDistributionRetrievalExecutor()
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured",
            "domain": "major_distribution", "purpose": "test",
            "query_text": "test",
            "structured_plan": {
                "table_profile": "major_distribution.v1",
                "query_profile": "major_distribution.record_list",
            },
            "tag_filters": {
                "regions": TagFilter(
                    tags=["浙江"], match_strategy="l1|l1.5",
                ).model_dump(),
            },
        })
        result = executor.execute(session, sub_query)
        assert result.status == StepStatus.COMPLETED
        assert {r["id"] for r in result.records} == {seeded["record_zj"]}
        assert result.retrieval_meta["tag_filter_target_ids_count"] == 1
        assert result.retrieval_meta["tag_filter_bucket_hit_counts"] == {"regions": 1}

    def test_empty_intersection_short_circuits_without_sql(self, session):
        seeded = _seed_major_distribution_min(session)
        # region seeded for zj, but not for js
        _seed_tag_index(
            session,
            target_type=TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
            target_id=seeded["record_zj"],
            asset_version_id=seeded["version_id"],
            tag_type="region", tag_value="浙江", tag_value_normalized="浙江",
        )
        _seed_tag_index(
            session,
            target_type=TagAssetIndexTargetType.MAJOR_DISTRIBUTION_RECORD,
            target_id=seeded["record_js"],
            asset_version_id=seeded["version_id"],
            tag_type="major", tag_value="其它专业", tag_value_normalized="其它专业",
        )
        executor = MajorDistributionRetrievalExecutor()
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured",
            "domain": "major_distribution", "purpose": "test",
            "query_text": "test",
            "structured_plan": {
                "table_profile": "major_distribution.v1",
                "query_profile": "major_distribution.record_list",
            },
            "tag_filters": {
                "regions": TagFilter(tags=["浙江"], match_strategy="l1|l1.5").model_dump(),
                "majors": TagFilter(tags=["其它专业"], match_strategy="l1|l1.5").model_dump(),
            },
        })
        result = executor.execute(session, sub_query)
        # zj matches regions, js matches majors — no overlap
        assert result.status == StepStatus.COMPLETED
        assert result.records == []
        assert "tag_filters_empty_intersection" in result.warnings

    def test_structured_filters_folded_into_plan(self, session):
        seeded = _seed_major_distribution_min(session)
        executor = MajorDistributionRetrievalExecutor()
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured",
            "domain": "major_distribution", "purpose": "test",
            "query_text": "test",
            "structured_plan": {
                "table_profile": "major_distribution.v1",
                "query_profile": "major_distribution.record_list",
                "filters": {},
            },
            "structured_filters": {"province_name": "浙江"},
        })
        result = executor.execute(session, sub_query)
        assert {r["id"] for r in result.records} == {seeded["record_zj"]}


# ---------------------------------------------------------------------------
# JobDemandRetrievalExecutor two-phase integration
# ---------------------------------------------------------------------------


class TestJobDemandTwoPhase:
    def test_record_list_tag_filter_hits_record_target(self, session):
        seeded = _seed_job_demand_min(session)
        _seed_tag_index(
            session,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            target_id=seeded["record_bj"],
            asset_version_id=seeded["version_id"],
            tag_type="region", tag_value="北京", tag_value_normalized="北京",
        )
        executor = JobDemandRetrievalExecutor()
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured", "domain": "job_demand",
            "purpose": "test", "query_text": "test",
            "structured_plan": {
                "table_profile": "job_demand.v1",
                "query_profile": "job_demand.record_list",
            },
            "tag_filters": {
                "regions": TagFilter(
                    tags=["北京"], match_strategy="l1|l1.5",
                ).model_dump(),
            },
        })
        result = executor.execute(session, sub_query)
        assert result.status == StepStatus.COMPLETED
        assert {r["id"] for r in result.records} == {seeded["record_bj"]}

    def test_requirement_keyword_tag_filter_hits_item_target(self, session):
        seeded = _seed_job_demand_min(session)
        _seed_tag_index(
            session,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_REQUIREMENT_ITEM,
            target_id=seeded["item_bj"],
            asset_version_id=seeded["version_id"],
            tag_type="ability", tag_value="直播运营",
            tag_value_normalized="直播运营",
        )
        executor = JobDemandRetrievalExecutor()
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured", "domain": "job_demand",
            "purpose": "test", "query_text": "test",
            "structured_plan": {
                "table_profile": "job_demand.v1",
                "query_profile": "job_demand.requirement_keyword",
            },
            "tag_filters": {
                "abilities": TagFilter(
                    tags=["直播运营"], match_strategy="l1|l1.5",
                ).model_dump(),
            },
        })
        result = executor.execute(session, sub_query)
        assert result.status == StepStatus.COMPLETED
        assert {r["id"] for r in result.records} == {seeded["item_bj"]}

    def test_aggregation_profile_narrows_group_via_tag_filter(self, session):
        seeded = _seed_job_demand_min(session)
        _seed_tag_index(
            session,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            target_id=seeded["record_bj"],
            asset_version_id=seeded["version_id"],
            tag_type="region", tag_value="北京", tag_value_normalized="北京",
        )
        executor = JobDemandRetrievalExecutor()
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured", "domain": "job_demand",
            "purpose": "test", "query_text": "test",
            "structured_plan": {
                "table_profile": "job_demand.v1",
                "query_profile": "job_demand.count_by_city",
                "group_by": ["city"],
                "metrics": [{"field": "record", "function": "count"}],
            },
            "tag_filters": {
                "regions": TagFilter(
                    tags=["北京"], match_strategy="l1|l1.5",
                ).model_dump(),
            },
        })
        result = executor.execute(session, sub_query)
        assert result.status == StepStatus.COMPLETED
        # only 北京市 series entry should exist (record-bj)
        cities = {row["city"] for row in result.aggregations[0].series}
        assert cities == {"北京市"}


# ---------------------------------------------------------------------------
# Competency fallback — profile has no tag_target_type
# ---------------------------------------------------------------------------


class TestCompetencyFallback:
    def test_tag_filters_emit_warning_but_do_not_fail(self, session):
        # PR-13b — ability_items_by_category / task_tree now support
        # tag_filters via OCCUPATIONAL_ABILITY_ITEM.  relations_by_ability
        # remains the fallback profile (polymorphic target_id).
        executor = CompetencyRetrievalExecutor()
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured",
            "domain": "competency_analysis", "purpose": "test",
            "query_text": "test",
            "structured_plan": {
                "table_profile": "ability_analysis.pgsd.v1",
                "query_profile": "competency.relations_by_ability",
                "filters": {"relation_type": "WORK_CONTENT_REQUIRES_ABILITY"},
            },
            "tag_filters": {
                "abilities": TagFilter(tags=["Python"]).model_dump(),
            },
        })
        result = executor.execute(session, sub_query)
        assert result.status == StepStatus.COMPLETED
        assert "tag_target_type_not_configured" in result.warnings
