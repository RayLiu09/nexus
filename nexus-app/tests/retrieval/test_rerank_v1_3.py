"""Rerank contracts at helper and supported document executor boundaries.

Document refs exercise tag score aggregation, WEIGHTED/LINEAR/RRF ordering
and the rerank switch. Structured field queries preserve SQL order without
tag scores; pure rerank helper tests retain order_by and kill-switch coverage.
"""

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
from nexus_app.retrieval.domain_registry import get_query_profile
from nexus_app.retrieval.executors.job_demand import JobDemandRetrievalExecutor
from nexus_app.retrieval.executors.unstructured import UnstructuredRetrievalExecutor
from nexus_app.retrieval.rerank import apply_weighted_rerank
from nexus_app.retrieval.schemas import QueryOrder, RetrievalSubQuery, StructuredPlan
from nexus_app.retrieval.tag_filter_execution import TagFilterExecutionResult
from nexus_app.retrieval.tag_filter_execution import execute_tag_filters
from nexus_app.retrieval.tag_resolver import TagAssetIndexResolver

from tests.fixtures.retrieval_documents import (
    seed_documents,
    add_tag,
    document_query,
    DocumentSearchAdapter,
)


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

    @pytest.mark.parametrize("combine", ["AND", "OR", "WEIGHTED", "LINEAR", "RRF"])
    def test_document_target_scores_follow_combine(self, session, combine):
        a, b = seed_documents(session)
        add_tag(session, a, "majors", "直播")
        add_tag(session, b, "majors", "直播")
        add_tag(session, a, "topics", "运营")
        query = document_query(
            {"majors": ["直播"], "topics": ["运营"]}, combine=combine
        )
        if combine == "LINEAR":
            query.combine_weights = {"majors": 1.0, "topics": 3.0}
        result = execute_tag_filters(
            sub_query=query,
            profile=get_query_profile("course_textbook", "semantic_chunk"),
            resolver=TagAssetIndexResolver(session),
        )
        assert result.target_ids == ({a} if combine == "AND" else {a, b})
        assert result.target_scores[a] > result.target_scores.get(b, 0)
        if combine in {"AND", "OR", "WEIGHTED"}:
            assert result.target_scores[a] == 2.0
            if combine != "AND":
                assert result.target_scores[b] == 1.0
        elif combine == "LINEAR":
            assert result.target_scores == {a: 4.0, b: 1.0}
        else:
            assert result.target_scores[a] == pytest.approx(2 / 61)
            assert result.target_scores[b] == pytest.approx(1 / 62)


# ---------------------------------------------------------------------------
# Executor integration
# ---------------------------------------------------------------------------


class TestExecutorIntegration:

    @pytest.mark.parametrize("enabled", [True, False])
    def test_document_rerank_and_kill_switch(self, session, enabled):
        a, b = seed_documents(session)
        add_tag(session, a, "majors", "直播")
        add_tag(session, b, "majors", "直播")
        add_tag(session, a, "topics", "运营")
        # Search deliberately puts the lower tag score first.
        query = document_query(
            {"majors": ["直播"], "topics": ["运营"]}, combine="WEIGHTED"
        )
        executor = UnstructuredRetrievalExecutor(
            search_adapter=DocumentSearchAdapter([b, a]), rerank_enabled=enabled
        )
        result = executor.execute(session, query)
        assert [i.normalized_ref_id for i in result.items] == (
            [a, b] if enabled else [b, a]
        )
        assert [i.score for i in result.items] == (
            [1.25, 0.75] if enabled else [0.5, 0.5]
        )
        assert (
            "unstructured_rerank_applied"
            if enabled
            else "unstructured_rerank_disabled_by_config"
        ) in result.warnings

    @pytest.mark.parametrize(
        "profile, prefix",
        [
            ("job_demand.record_list", "record"),
            ("job_demand.requirement_keyword", "item"),
        ],
    )
    def test_structured_order_is_domain_order_without_tag_scores(
        self, session, profile, prefix
    ):
        seeded = _seed_job_demand(session)
        query = _make_sub_query(order_by=[QueryOrder(field="city", direction="desc")])
        query.structured_plan.query_profile = profile
        result = JobDemandRetrievalExecutor(rerank_enabled=True).execute(session, query)
        assert [r["id"] for r in result.records] == [
            seeded[f"{prefix}_bj"],
            seeded[f"{prefix}_sh"],
        ]
        assert all("score" not in r for r in result.records)
        assert not any("rerank" in w for w in result.warnings)

    def test_aggregation_profile_never_injects_scores(self, session):
        _seed_job_demand(session)
        query = _make_sub_query()
        query.structured_plan = StructuredPlan(
            table_profile="job_demand.v1",
            query_profile="job_demand.count_by_city",
            filters={"city": "北京市"},
            group_by=["city"],
            metrics=[{"field": "record", "function": "count"}],
        )
        result = JobDemandRetrievalExecutor(rerank_enabled=True).execute(session, query)
        assert len(result.aggregations[0].series) == 1
        assert result.aggregations[0].series[0]["value"] == 1
        assert "score" not in result.aggregations[0].series[0]
        assert not any("rerank" in w for w in result.warnings)


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
