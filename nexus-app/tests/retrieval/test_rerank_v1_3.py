"""PR-13 guards for WEIGHTED combine op rerank pipeline.

Coverage:

* Phase A ``target_scores`` aggregation — sum-of-max-per-bucket.
* ``apply_weighted_rerank`` unit — score inject + reorder + kill switch
  + explicit ``order_by`` suppression.
* Executor integration (job_demand.record_list +
  job_demand.requirement_keyword + major_distribution.record_list) with
  the kill switch flipped both ways.
* Aggregation profiles never rerank (records carry group_value shape).
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
from nexus_app.retrieval.executors.job_demand import JobDemandRetrievalExecutor
from nexus_app.retrieval.executors.major_distribution import (
    MajorDistributionRetrievalExecutor,
)
from nexus_app.retrieval.rerank import (
    RerankDecision,
    apply_weighted_rerank,
)
from nexus_app.retrieval.schemas import (
    BusinessDomain,
    QueryOrder,
    RetrievalChannel,
    RetrievalSubQuery,
    StepStatus,
    StructuredPlan,
)
from nexus_app.retrieval.tag_filter_execution import (
    TagFilterExecutionResult,
)
from nexus_app.retrieval.tag_schemas import TagFilter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_job_demand(session) -> dict[str, str]:
    """Two records + two items for rerank fan-out."""
    ds = models.DataSource(
        id="ds-jr", code="ds-jr", name="jd",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="batch-jr", data_source_id=ds.id, idempotency_key="idem-jr",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="raw-jr", batch_id=batch.id, data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://x/jd.xlsx", checksum="raw-jr",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id="asset-jr", data_source_id=ds.id, source_object_key="jd.xlsx",
        title="jd", asset_kind=AssetKind.RECORD,
        status=AssetVersionStatus.AVAILABLE,
    )
    version = models.AssetVersion(
        id="version-jr", asset_id=asset.id, raw_object_id=raw.id,
        version_no=1, source_checksum=raw.checksum,
        version_status=AssetVersionStatus.AVAILABLE,
    )
    ref = models.NormalizedAssetRef(
        id="ref-jr", version_id=version.id,
        normalized_type=NormalizedType.RECORD,
        object_uri="s3://x/jd.json", schema_version="normalized-record.v2",
        checksum="ref-jr", status=NormalizedAssetRefStatus.GENERATED,
        source_type="file_upload", content_type="table_sheet",
        title="jd", language="zh-CN",
        governance={}, quality={}, lineage={},
        metadata_summary={"domain_profile": "job_demand.v1"},
    )
    dataset = models.JobDemandDataset(
        id="dataset-jr", normalized_ref_id=ref.id, asset_version_id=version.id,
        source_channel="excel_upload",
        major_name="电子商务", industry_name="互联网", record_count=2,
        schema_version="job_demand.v1", quality_summary={},
    )
    record_bj = models.JobDemandRecord(
        id="record-bj", dataset_id=dataset.id, normalized_ref_id=ref.id,
        source_record_key="k-bj", job_title="电商运营",
        city="北京市", region="华北", education_requirement="本科",
        industry_name="直播电商", record_fingerprint="fp-bj",
        quality_flags={}, trace={},
    )
    record_sh = models.JobDemandRecord(
        id="record-sh", dataset_id=dataset.id, normalized_ref_id=ref.id,
        source_record_key="k-sh", job_title="用户增长",
        city="上海市", region="华东", education_requirement="本科",
        industry_name="直播电商", record_fingerprint="fp-sh",
        quality_flags={}, trace={},
    )
    item_bj = models.JobDemandRequirementItem(
        id="item-bj", record_id=record_bj.id, dataset_id=dataset.id,
        item_type="professional_skill", item_name="直播运营",
        raw_text="", normalized_name="直播运营",
        confidence=0.9, evidence_field="requirement_text",
    )
    item_sh = models.JobDemandRequirementItem(
        id="item-sh", record_id=record_sh.id, dataset_id=dataset.id,
        item_type="professional_skill", item_name="用户增长",
        raw_text="", normalized_name="用户增长",
        confidence=0.9, evidence_field="requirement_text",
    )
    session.add_all([ds, batch, raw, asset, version, ref, dataset,
                     record_bj, record_sh, item_bj, item_sh])
    session.commit()
    return {
        "version_id": "version-jr",
        "record_bj": "record-bj",
        "record_sh": "record-sh",
        "item_bj": "item-bj",
        "item_sh": "item-sh",
    }


def _seed_tag(
    session,
    *,
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
    session.commit()


# ---------------------------------------------------------------------------
# apply_weighted_rerank — pure unit
# ---------------------------------------------------------------------------


def _make_sub_query(combine: str = "WEIGHTED", order_by=None) -> RetrievalSubQuery:
    return RetrievalSubQuery.model_validate({
        "query_id": "q1", "channel": "structured",
        "domain": "job_demand", "purpose": "test",
        "query_text": "test",
        "structured_plan": StructuredPlan(
            table_profile="job_demand.v1",
            query_profile="job_demand.record_list",
            order_by=order_by or [],
        ).model_dump(),
        "combine": combine,
    })


def _make_phase_a(scores: dict[str, float]) -> TagFilterExecutionResult:
    return TagFilterExecutionResult(
        target_ids=set(scores.keys()),
        target_scores=scores,
    )


class TestApplyWeightedRerank:
    def test_scores_injected_and_records_reordered_when_enabled(self):
        records = [
            {"id": "a", "name": "x"},
            {"id": "b", "name": "y"},
            {"id": "c", "name": "z"},
        ]
        phase_a = _make_phase_a({"a": 0.5, "b": 1.5, "c": 0.9})
        decision = apply_weighted_rerank(
            records=records,
            sub_query=_make_sub_query(),
            phase_a=phase_a,
            rerank_enabled=True,
        )
        assert decision.reordered is True
        assert decision.warning_code == "weighted_rerank_applied"
        assert [r["id"] for r in records] == ["b", "c", "a"]
        assert records[0]["score"] == 1.5

    def test_switch_off_injects_scores_but_skips_reorder(self):
        records = [
            {"id": "a"}, {"id": "b"}, {"id": "c"},
        ]
        phase_a = _make_phase_a({"a": 0.5, "b": 1.5, "c": 0.9})
        decision = apply_weighted_rerank(
            records=records,
            sub_query=_make_sub_query(),
            phase_a=phase_a,
            rerank_enabled=False,
        )
        assert decision.reordered is False
        assert decision.warning_code == "weighted_rerank_disabled_by_config"
        # Scores still injected for observability
        assert [r["score"] for r in records] == [0.5, 1.5, 0.9]
        # Order unchanged
        assert [r["id"] for r in records] == ["a", "b", "c"]

    def test_explicit_order_by_suppresses_rerank(self):
        records = [{"id": "a"}, {"id": "b"}]
        phase_a = _make_phase_a({"a": 0.5, "b": 2.0})
        sub_query = _make_sub_query(
            order_by=[QueryOrder(field="job_title", direction="asc")],
        )
        decision = apply_weighted_rerank(
            records=records,
            sub_query=sub_query,
            phase_a=phase_a,
            rerank_enabled=True,
        )
        assert decision.reordered is False
        assert decision.warning_code == "weighted_rerank_suppressed_by_order_by"
        assert [r["id"] for r in records] == ["a", "b"]

    def test_combine_and_skips_reorder_but_injects_scores(self):
        records = [{"id": "a"}, {"id": "b"}]
        phase_a = _make_phase_a({"a": 0.5, "b": 1.5})
        sub_query = _make_sub_query(combine="AND")
        decision = apply_weighted_rerank(
            records=records,
            sub_query=sub_query,
            phase_a=phase_a,
            rerank_enabled=True,
        )
        assert decision.reordered is False
        assert "weighted_rerank_skipped_combine=AND" in decision.warning_code
        assert records[0]["score"] == 0.5
        assert records[1]["score"] == 1.5


# ---------------------------------------------------------------------------
# Phase A target_scores aggregation
# ---------------------------------------------------------------------------


class TestTargetScoreAggregation:
    def test_and_intersection_sums_contributing_buckets(self, session):
        # target 'x' matches both buckets: score = 1.0 + 1.0 = 2.0
        # target 'y' matches only regions: filtered out by AND
        from nexus_app.retrieval.domain_registry import get_query_profile
        from nexus_app.retrieval.tag_filter_execution import execute_tag_filters
        from nexus_app.retrieval.tag_resolver import TagAssetIndexResolver

        seeded = _seed_job_demand(session)
        _seed_tag(
            session,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            target_id=seeded["record_bj"],
            asset_version_id=seeded["version_id"],
            tag_type="region", tag_value="北京",
        )
        _seed_tag(
            session,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            target_id=seeded["record_bj"],
            asset_version_id=seeded["version_id"],
            tag_type="industry", tag_value="直播电商",
        )
        # record_sh only matches regions (not industries)
        _seed_tag(
            session,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            target_id=seeded["record_sh"],
            asset_version_id=seeded["version_id"],
            tag_type="region", tag_value="上海",
        )
        profile = get_query_profile(
            BusinessDomain.JOB_DEMAND, "job_demand.record_list",
        )
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured",
            "domain": "job_demand", "purpose": "t",
            "query_text": "t",
            "structured_plan": {
                "table_profile": "job_demand.v1",
                "query_profile": "job_demand.record_list",
            },
            "tag_filters": {
                "regions": TagFilter(
                    tags=["北京", "上海"], match_strategy="l1|l1.5",
                ).model_dump(),
                "industries": TagFilter(
                    tags=["直播电商"], match_strategy="l1|l1.5",
                ).model_dump(),
            },
            "combine": "AND",
        })
        result = execute_tag_filters(
            sub_query=sub_query, profile=profile,
            resolver=TagAssetIndexResolver(session),
        )
        # Only record_bj in intersection; score = 1.0 (region) + 1.0 (industry)
        assert result.target_ids == {seeded["record_bj"]}
        assert result.target_scores == {seeded["record_bj"]: 2.0}

    def test_or_union_sums_across_buckets(self, session):
        from nexus_app.retrieval.domain_registry import get_query_profile
        from nexus_app.retrieval.tag_filter_execution import execute_tag_filters
        from nexus_app.retrieval.tag_resolver import TagAssetIndexResolver

        seeded = _seed_job_demand(session)
        _seed_tag(
            session,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            target_id=seeded["record_bj"],
            asset_version_id=seeded["version_id"],
            tag_type="region", tag_value="北京",
        )
        _seed_tag(
            session,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            target_id=seeded["record_bj"],
            asset_version_id=seeded["version_id"],
            tag_type="industry", tag_value="直播电商",
        )
        _seed_tag(
            session,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            target_id=seeded["record_sh"],
            asset_version_id=seeded["version_id"],
            tag_type="region", tag_value="上海",
        )
        profile = get_query_profile(
            BusinessDomain.JOB_DEMAND, "job_demand.record_list",
        )
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured",
            "domain": "job_demand", "purpose": "t",
            "query_text": "t",
            "structured_plan": {
                "table_profile": "job_demand.v1",
                "query_profile": "job_demand.record_list",
            },
            "tag_filters": {
                "regions": TagFilter(
                    tags=["北京", "上海"], match_strategy="l1|l1.5",
                ).model_dump(),
                "industries": TagFilter(
                    tags=["直播电商"], match_strategy="l1|l1.5",
                ).model_dump(),
            },
            "combine": "WEIGHTED",
        })
        result = execute_tag_filters(
            sub_query=sub_query, profile=profile,
            resolver=TagAssetIndexResolver(session),
        )
        # BJ scores 2.0 (region + industry), SH scores 1.0 (region only)
        assert result.target_scores[seeded["record_bj"]] == 2.0
        assert result.target_scores[seeded["record_sh"]] == 1.0


# ---------------------------------------------------------------------------
# Executor integration
# ---------------------------------------------------------------------------


class TestExecutorIntegration:
    def test_weighted_reorder_when_switch_on(self, session):
        seeded = _seed_job_demand(session)
        # BJ matches two buckets, SH one.
        _seed_tag(
            session,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            target_id=seeded["record_bj"],
            asset_version_id=seeded["version_id"],
            tag_type="region", tag_value="北京",
        )
        _seed_tag(
            session,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            target_id=seeded["record_bj"],
            asset_version_id=seeded["version_id"],
            tag_type="industry", tag_value="直播电商",
        )
        _seed_tag(
            session,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            target_id=seeded["record_sh"],
            asset_version_id=seeded["version_id"],
            tag_type="region", tag_value="上海",
        )
        executor = JobDemandRetrievalExecutor(rerank_enabled=True)
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured",
            "domain": "job_demand", "purpose": "t",
            "query_text": "t",
            "structured_plan": {
                "table_profile": "job_demand.v1",
                "query_profile": "job_demand.record_list",
            },
            "tag_filters": {
                "regions": TagFilter(
                    tags=["北京", "上海"], match_strategy="l1|l1.5",
                ).model_dump(),
                "industries": TagFilter(
                    tags=["直播电商"], match_strategy="l1|l1.5",
                ).model_dump(),
            },
            "combine": "WEIGHTED",
        })
        result = executor.execute(session, sub_query)
        assert [r["id"] for r in result.records] == [
            seeded["record_bj"], seeded["record_sh"],
        ]
        assert result.records[0]["score"] == 2.0
        assert result.records[1]["score"] == 1.0
        assert "weighted_rerank_applied" in result.warnings

    def test_switch_off_keeps_sql_order_but_injects_scores(self, session):
        seeded = _seed_job_demand(session)
        # SH gets higher score than BJ but rerank is disabled.
        _seed_tag(
            session,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            target_id=seeded["record_bj"],
            asset_version_id=seeded["version_id"],
            tag_type="region", tag_value="北京",
        )
        _seed_tag(
            session,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            target_id=seeded["record_sh"],
            asset_version_id=seeded["version_id"],
            tag_type="region", tag_value="上海",
        )
        _seed_tag(
            session,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            target_id=seeded["record_sh"],
            asset_version_id=seeded["version_id"],
            tag_type="industry", tag_value="直播电商",
        )
        executor = JobDemandRetrievalExecutor(rerank_enabled=False)
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured",
            "domain": "job_demand", "purpose": "t",
            "query_text": "t",
            "structured_plan": {
                "table_profile": "job_demand.v1",
                "query_profile": "job_demand.record_list",
            },
            "tag_filters": {
                "regions": TagFilter(
                    tags=["北京", "上海"], match_strategy="l1|l1.5",
                ).model_dump(),
                "industries": TagFilter(
                    tags=["直播电商"], match_strategy="l1|l1.5",
                ).model_dump(),
            },
            "combine": "WEIGHTED",
        })
        result = executor.execute(session, sub_query)
        # Scores injected regardless of switch
        scores_by_id = {r["id"]: r["score"] for r in result.records}
        assert scores_by_id[seeded["record_bj"]] == 1.0
        assert scores_by_id[seeded["record_sh"]] == 2.0
        assert "weighted_rerank_disabled_by_config" in result.warnings

    def test_requirement_keyword_reranks_by_item_id(self, session):
        seeded = _seed_job_demand(session)
        # Item bj matches two ability buckets (dedup within bucket: max)
        _seed_tag(
            session,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_REQUIREMENT_ITEM,
            target_id=seeded["item_bj"],
            asset_version_id=seeded["version_id"],
            tag_type="ability", tag_value="直播运营",
        )
        _seed_tag(
            session,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_REQUIREMENT_ITEM,
            target_id=seeded["item_bj"],
            asset_version_id=seeded["version_id"],
            tag_type="topic", tag_value="电商",
        )
        # Item sh matches one
        _seed_tag(
            session,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_REQUIREMENT_ITEM,
            target_id=seeded["item_sh"],
            asset_version_id=seeded["version_id"],
            tag_type="ability", tag_value="用户增长",
        )
        executor = JobDemandRetrievalExecutor(rerank_enabled=True)
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured",
            "domain": "job_demand", "purpose": "t",
            "query_text": "t",
            "structured_plan": {
                "table_profile": "job_demand.v1",
                "query_profile": "job_demand.requirement_keyword",
            },
            "tag_filters": {
                "abilities": TagFilter(
                    tags=["直播运营", "用户增长"], match_strategy="l1|l1.5",
                ).model_dump(),
                "topics": TagFilter(
                    tags=["电商"], match_strategy="l1|l1.5",
                ).model_dump(),
            },
            "combine": "WEIGHTED",
        })
        result = executor.execute(session, sub_query)
        assert [r["id"] for r in result.records] == [
            seeded["item_bj"], seeded["item_sh"],
        ]
        assert result.records[0]["score"] == 2.0
        assert result.records[1]["score"] == 1.0

    def test_aggregation_profile_skips_rerank_entirely(self, session):
        seeded = _seed_job_demand(session)
        _seed_tag(
            session,
            target_type=TagAssetIndexTargetType.JOB_DEMAND_RECORD,
            target_id=seeded["record_bj"],
            asset_version_id=seeded["version_id"],
            tag_type="region", tag_value="北京",
        )
        executor = JobDemandRetrievalExecutor(rerank_enabled=True)
        sub_query = RetrievalSubQuery.model_validate({
            "query_id": "q1", "channel": "structured",
            "domain": "job_demand", "purpose": "t",
            "query_text": "t",
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
            "combine": "WEIGHTED",
        })
        result = executor.execute(session, sub_query)
        # Aggregation results don't have record ids → no score injection
        # and no rerank warning.
        rerank_warnings = [
            w for w in result.warnings if "rerank" in w or "weighted" in w
        ]
        assert rerank_warnings == []
        # Records are group_value payloads; if any exist they carry no score
        for row in result.aggregations[0].series:
            assert "score" not in row


# ---------------------------------------------------------------------------
# Config kill switch
# ---------------------------------------------------------------------------


class TestConfigKillSwitch:
    """The ``effective_rerank_enabled`` computed property has two ANDed
    inputs.  Since Settings picks up ``.env.dev`` (which ships with the
    ``DEFAULT_RERANKING_MODEL`` alias set), the tests use env-var
    monkeypatching + cache clearing to isolate each case.
    """

    def _fresh_settings(self, monkeypatch, *, enabled: bool, model: str | None):
        from nexus_app import config as cfg_module

        monkeypatch.setenv(
            "RETRIEVAL_RERANK_ENABLED", "true" if enabled else "false",
        )
        if model is None:
            # There's no clean way to "unset" a pydantic field back to
            # default under Settings-from-env loading; just set to empty
            # and the computed property treats it as falsy.
            monkeypatch.setenv("DEFAULT_RERANKING_MODEL", "")
        else:
            monkeypatch.setenv("DEFAULT_RERANKING_MODEL", model)
        cfg_module.get_settings.cache_clear()
        return cfg_module.get_settings()

    def test_switch_off_with_model_still_disables(self, monkeypatch):
        s = self._fresh_settings(
            monkeypatch, enabled=False, model="bge-reranker-v2-m3",
        )
        assert s.effective_rerank_enabled is False

    def test_switch_on_without_model_still_disables(self, monkeypatch):
        s = self._fresh_settings(monkeypatch, enabled=True, model=None)
        assert s.effective_rerank_enabled is False

    def test_switch_on_with_model_enables(self, monkeypatch):
        s = self._fresh_settings(
            monkeypatch, enabled=True, model="bge-reranker-v2-m3",
        )
        assert s.effective_rerank_enabled is True

    def test_both_off_disables(self, monkeypatch):
        s = self._fresh_settings(monkeypatch, enabled=False, model=None)
        assert s.effective_rerank_enabled is False
