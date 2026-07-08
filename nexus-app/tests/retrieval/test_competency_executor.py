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
from nexus_app.retrieval.executors.competency import CompetencyRetrievalExecutor
from nexus_app.retrieval.schemas import QueryMetric, QueryOrder, RetrievalSubQuery, StructuredPlan
from nexus_app.retrieval.sql_guardrails import StructuredPlanGuardrailError


def _seed_competency(session) -> None:
    profile = models.AbilityAnalysisProfile(
        id="profile-ca",
        model_code="PGSD",
        model_name="职业能力分析 PGSD 模型",
        schema_version="ability_analysis.pgsd.v1",
        category_schema=[],
        code_pattern={},
        relation_schema={},
        detector_rules={},
        is_active=True,
        is_builtin=True,
    )
    ds = models.DataSource(
        id="ds-ca",
        code="ds-ca",
        name="competency",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="batch-ca",
        data_source_id=ds.id,
        idempotency_key="idem-ca",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="raw-ca",
        batch_id=batch.id,
        data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://bucket/raw/ca.xlsx",
        checksum="raw-ca",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id="asset-ca",
        data_source_id=ds.id,
        source_object_key="ca.xlsx",
        title="职业能力分析",
        asset_kind=AssetKind.RECORD,
        status=AssetVersionStatus.AVAILABLE,
    )
    version = models.AssetVersion(
        id="version-ca",
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=1,
        source_checksum=raw.checksum,
        version_status=AssetVersionStatus.AVAILABLE,
    )
    ref = models.NormalizedAssetRef(
        id="ref-ca",
        version_id=version.id,
        normalized_type=NormalizedType.RECORD,
        object_uri="s3://bucket/normalized/ref-ca.json",
        schema_version="normalized-record.v2",
        checksum="ref-ca",
        status=NormalizedAssetRefStatus.GENERATED,
        source_type="file_upload",
        content_type="table_sheet",
        title="职业能力分析",
        language="zh-CN",
        governance={},
        quality={},
        lineage={},
        metadata_summary={"domain_profile": "ability_analysis.pgsd.v1"},
    )
    analysis = models.OccupationalAbilityAnalysis(
        id="analysis-ca",
        normalized_ref_id=ref.id,
        asset_version_id=version.id,
        profile_id=profile.id,
        analysis_model="PGSD",
        major_name="大数据技术应用",
        schema_version="ability_analysis.pgsd.v1",
        task_count=1,
        work_content_count=1,
        ability_item_count=2,
        quality_summary={},
    )
    task = models.OccupationalWorkTask(
        id="task-ca",
        analysis_id=analysis.id,
        task_code="1",
        task_name="数据采集",
        task_description="采集数据",
        task_description_structured={},
        display_order=1,
        trace={"sheet": "任务", "row": 2},
    )
    content = models.OccupationalWorkContent(
        id="content-ca",
        analysis_id=analysis.id,
        task_id=task.id,
        content_code="1.1",
        content_name="日志系统数据采集",
        display_order=1,
        trace={"sheet": "任务", "row": 3},
    )
    ability_1 = models.OccupationalAbilityItem(
        id="ability-ca-1",
        analysis_id=analysis.id,
        task_id=task.id,
        work_content_id=content.id,
        ability_code="P-1.1.1",
        ability_major_category_code="P",
        ability_major_category_name="职业能力",
        ability_sequence="1.1.1",
        ability_content="能够采集日志",
        normalized_terms={},
        quality_flags={},
        trace={"sheet": "能力", "row": 4},
    )
    ability_2 = models.OccupationalAbilityItem(
        id="ability-ca-2",
        analysis_id=analysis.id,
        task_id=task.id,
        work_content_id=None,
        ability_code="G-1",
        ability_major_category_code="G",
        ability_major_category_name="通用能力",
        ability_sequence="1",
        ability_content="具备沟通能力",
        normalized_terms={},
        quality_flags={},
        trace={"sheet": "能力", "row": 5},
    )
    relation = models.OccupationalAbilityRelation(
        id="rel-ca-1",
        analysis_id=analysis.id,
        source_type="work_content",
        source_id=content.id,
        relation_type="WORK_CONTENT_REQUIRES_ABILITY",
        target_type="ability_item",
        target_id=ability_1.id,
        evidence={"sheet": "关系", "row": 6},
    )
    session.add_all([
        profile,
        ds,
        batch,
        raw,
        asset,
        version,
        ref,
        analysis,
        task,
        content,
        ability_1,
        ability_2,
        relation,
    ])
    session.commit()


def _sub_query(plan: StructuredPlan) -> RetrievalSubQuery:
    return RetrievalSubQuery.model_validate(
        {
            "query_id": "q1",
            "channel": "structured",
            "domain": "competency_analysis",
            "purpose": "competency_query",
            "query_text": "大数据技术应用职业能力",
            "structured_plan": plan.model_dump(),
        }
    )


def test_competency_executor_returns_task_tree(session):
    _seed_competency(session)
    result = CompetencyRetrievalExecutor().execute(
        session,
        _sub_query(
            StructuredPlan(
                table_profile="ability_analysis.pgsd.v1",
                query_profile="competency.task_tree",
                filters={"major_name": "大数据技术"},
                order_by=[QueryOrder(field="task_code", direction="asc")],
            )
        ),
    )

    assert result.result_shape == "task_tree"
    assert result.records[0]["task"]["task_name"] == "数据采集"
    assert result.records[0]["ability_item"]["ability_code"] == "P-1.1.1"
    assert result.source_refs[0].asset_id == "asset-ca"
    assert result.source_refs[0].record_ref == "occupational_work_task:task-ca"


def test_competency_executor_returns_category_aggregation(session):
    _seed_competency(session)
    result = CompetencyRetrievalExecutor().execute(
        session,
        _sub_query(
            StructuredPlan(
                table_profile="ability_analysis.pgsd.v1",
                query_profile="competency.ability_items_by_category",
                group_by=["ability_major_category_code"],
                metrics=[QueryMetric(field="record", function="count")],
            )
        ),
    )

    assert result.result_shape == "aggregation"
    assert result.aggregations[0].series == [
        {"ability_major_category_code": "G", "value": 1},
        {"ability_major_category_code": "P", "value": 1},
    ]
    assert {ref.record_ref for ref in result.source_refs} == {
        "occupational_ability_item:ability-ca-1",
        "occupational_ability_item:ability-ca-2",
    }


def test_competency_executor_returns_relations(session):
    _seed_competency(session)
    result = CompetencyRetrievalExecutor().execute(
        session,
        _sub_query(
            StructuredPlan(
                table_profile="ability_analysis.pgsd.v1",
                query_profile="competency.relations_by_ability",
                filters={"relation_type": "WORK_CONTENT_REQUIRES_ABILITY"},
            )
        ),
    )

    assert result.result_shape == "relations"
    assert result.records[0]["relation_type"] == "WORK_CONTENT_REQUIRES_ABILITY"
    assert result.source_refs[0].record_ref == "occupational_ability_relation:rel-ca-1"
    assert result.source_refs[0].locator == {"sheet": "关系", "row": 6}


def test_competency_executor_rejects_non_whitelisted_filter(session):
    _seed_competency(session)
    plan = StructuredPlan(
        table_profile="ability_analysis.pgsd.v1",
        query_profile="competency.task_tree",
        filters={"school_name": "某学校"},
    )

    with pytest.raises(StructuredPlanGuardrailError):
        CompetencyRetrievalExecutor().execute(session, _sub_query(plan))
