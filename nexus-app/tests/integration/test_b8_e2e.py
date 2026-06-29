"""B8.3 — combined sample-1 + sample-2 staging E2E.

Acceptance per `pipeline_b_implementation_plan.md §B8`:
- combined build produces JobDemandRecord / Skill / ProfessionalLiteracy
  + WorkTask / WorkContent / Ability nodes
- emits at least 3 edge types: JOB_RECORD_HAS_SKILL,
  TASK_HAS_WORK_CONTENT, WORK_CONTENT_REQUIRES_ABILITY
- when `ability_analysis_source_dataset` link exists, emits
  ABILITY_DERIVED_FROM_JOB_REQUIREMENT edges
- quality_summary reports orphan_nodes_count

This file sets up the source rows the way B4 + B5 + B6 would have, then
calls `build_capability_staging` directly (worker wiring is exercised by
the existing per-stage tests and by `tests/test_b8_capability_graph.py`).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from nexus_app import models
from nexus_app.capability_graph import build_capability_staging
from nexus_app.capability_graph.whitelists import (
    BuildStatus,
    BuildType,
    EdgeType,
    NodeType,
)
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
)


@pytest.fixture
def sample_combined(session):
    """Sample-1-shaped + sample-2-shaped tree under one normalized_ref."""
    asset = models.Asset(
        id="a", asset_kind=AssetKind.RECORD, title="t",
        data_source_id="src", source_object_key="k",
    )
    raw = models.RawObject(
        id="r", data_source_id="src", batch_id="b",
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://b/x", checksum="cs", size_bytes=1,
        status=RawObjectStatus.RAW_PERSISTED, metadata_summary={},
    )
    version = models.AssetVersion(
        id="v", asset_id="a", raw_object_id="r",
        version_no=1, source_checksum="cs",
        version_status=AssetVersionStatus.PROCESSING,
        metadata_summary={},
    )
    ref = models.NormalizedAssetRef(
        id="ref", version_id="v",
        normalized_type=NormalizedType.RECORD,
        object_uri="s3://b/x.json",
        schema_version="normalized-record.v2",
        checksum="cs",
        status=NormalizedAssetRefStatus.GENERATED,
    )
    # job_demand side (sample 1 shape)
    dataset = models.JobDemandDataset(
        id="ds", normalized_ref_id="ref", asset_version_id="v",
        source_channel="excel_upload", record_count=3,
        schema_version="job_demand.v1",
    )
    session.add_all([asset, raw, version, ref, dataset])
    session.flush()
    records = [
        models.JobDemandRecord(
            id=f"rec-{i}", dataset_id="ds", normalized_ref_id="ref",
            source_record_key=f"r{i}", job_title="数据分析师",
            company_name=co, city=city, record_fingerprint=f"fp-{i}",
        )
        for i, (co, city) in enumerate([
            ("字节", "北京"), ("美团", "上海"), ("阿里", "杭州"),
        ], start=1)
    ]
    session.add_all(records)
    session.flush()
    items = [
        models.JobDemandRequirementItem(
            id="it-skill-py", record_id="rec-1", dataset_id="ds",
            item_type="professional_skill", item_name="Python",
            normalized_name="python", confidence=Decimal("0.92"),
        ),
        models.JobDemandRequirementItem(
            id="it-skill-sql", record_id="rec-2", dataset_id="ds",
            item_type="tool", item_name="SQL",
            normalized_name="sql", confidence=Decimal("0.90"),
        ),
        models.JobDemandRequirementItem(
            id="it-lit", record_id="rec-3", dataset_id="ds",
            item_type="professional_literacy", item_name="团队协作",
            confidence=Decimal("0.88"),
        ),
        models.JobDemandRequirementItem(
            id="it-cert", record_id="rec-3", dataset_id="ds",
            item_type="certificate", item_name="数据分析师证书",
            normalized_name="数据分析师证书", confidence=Decimal("0.86"),
        ),
        models.JobDemandRequirementItem(
            id="it-work", record_id="rec-1", dataset_id="ds",
            item_type="work_task_candidate", item_name="经营数据看板维护",
            normalized_name="经营数据看板维护", confidence=Decimal("0.82"),
        ),
    ]
    session.add_all(items)
    session.flush()

    # ability_analysis side (sample 2 shape, minimal)
    profile = models.AbilityAnalysisProfile(
        id="prof-pgsd", model_code="PGSD", model_name="PGSD",
        schema_version="ability_analysis.pgsd.v1",
        category_schema=[{"code": "P"}, {"code": "G"}, {"code": "S"}, {"code": "D"}],
        code_pattern={
            "P": {"regex": r"^P-\d+\.\d+\.\d+$", "segments": 3,
                  "requires_work_content": True},
            "G": {"regex": r"^G-\d+\.\d+$", "segments": 2,
                  "requires_work_content": False},
            "S": {"regex": r"^S-\d+\.\d+$", "segments": 2,
                  "requires_work_content": False},
            "D": {"regex": r"^D-\d+\.\d+$", "segments": 2,
                  "requires_work_content": False},
        },
        is_active=True, is_builtin=True,
    )
    analysis = models.OccupationalAbilityAnalysis(
        id="ana", normalized_ref_id="ref", asset_version_id="v",
        profile_id="prof-pgsd", analysis_model="PGSD",
        schema_version="ability_analysis.pgsd.v1",
    )
    session.add_all([profile, analysis])
    session.flush()
    task = models.OccupationalWorkTask(
        id="task", analysis_id="ana", task_code="1", task_name="数据采集",
        task_description="x", task_description_structured={}, display_order=1,
    )
    wc = models.OccupationalWorkContent(
        id="wc", analysis_id="ana", task_id="task",
        content_code="1.1", content_name="日志采集", display_order=1,
    )
    session.add_all([task, wc])
    session.flush()
    abilities = [
        models.OccupationalAbilityItem(
            id="ab-p", analysis_id="ana", task_id="task", work_content_id="wc",
            ability_code="P-1.1.1", ability_major_category_code="P",
            ability_major_category_name="职业能力", ability_sequence="1.1.1",
            ability_content="能用工具采集日志数据",
            confidence=Decimal("0.92"),
        ),
        models.OccupationalAbilityItem(
            id="ab-g", analysis_id="ana", task_id="task", work_content_id=None,
            ability_code="G-1.1", ability_major_category_code="G",
            ability_major_category_name="通用能力", ability_sequence="1.1",
            ability_content="团队协作能力",
        ),
    ]
    session.add_all(abilities)
    session.commit()
    return ref, dataset, analysis


class TestCombinedBuildAcceptance:
    def test_combined_build_emits_all_required_node_types(
        self, session, sample_combined,
    ):
        ref, _, _ = sample_combined
        result = build_capability_staging(
            session, ref, build_type=BuildType.COMBINED,
        )
        session.commit()

        nodes = list(session.scalars(
            select(models.CapabilityGraphStagingNode).where(
                models.CapabilityGraphStagingNode.build_id == result.build_id
            )
        ))
        types_present = {n.node_type for n in nodes}
        # B8 acceptance: all 6 first-class node types must appear.
        assert {
            NodeType.JOB_DEMAND_RECORD,
            NodeType.JOB_ROLE,
            NodeType.SKILL,
            NodeType.PROFESSIONAL_LITERACY,
            NodeType.WORK_TASK,
            NodeType.WORK_CONTENT,
            NodeType.ABILITY,
        } <= types_present
        # CourseModule is reserved but MUST NOT appear in P0 output.
        assert NodeType.COURSE_MODULE not in types_present

    def test_combined_build_emits_at_least_three_edge_types(
        self, session, sample_combined,
    ):
        ref, _, _ = sample_combined
        result = build_capability_staging(
            session, ref, build_type=BuildType.COMBINED,
        )
        session.commit()

        edges = list(session.scalars(
            select(models.CapabilityGraphStagingEdge).where(
                models.CapabilityGraphStagingEdge.build_id == result.build_id
            )
        ))
        types = {e.edge_type for e in edges}
        # B8 acceptance: three baseline edge types must appear.
        assert {
            EdgeType.JOB_RECORD_HAS_SKILL,
            EdgeType.JOB_RECORD_HAS_WORK_CONTENT,
            EdgeType.TASK_HAS_WORK_CONTENT,
            EdgeType.TASK_REQUIRES_ABILITY,
            EdgeType.WORK_CONTENT_REQUIRES_ABILITY,
        } <= types

    def test_job_demand_work_task_candidate_becomes_work_content(
        self, session, sample_combined,
    ):
        ref, _, _ = sample_combined
        result = build_capability_staging(
            session, ref, build_type=BuildType.JOB_DEMAND,
        )
        session.commit()

        nodes = list(session.scalars(
            select(models.CapabilityGraphStagingNode).where(
                models.CapabilityGraphStagingNode.build_id == result.build_id
            )
        ))
        work_contents = [
            node for node in nodes
            if node.node_type == NodeType.WORK_CONTENT
            and node.properties.get("item_type") == "work_task_candidate"
        ]
        assert [node.display_name for node in work_contents] == ["经营数据看板维护"]

    def test_combined_build_emits_derived_edges_when_link_present(
        self, session, sample_combined,
    ):
        ref, dataset, analysis = sample_combined
        # Pin the cross-domain evidence link.
        link = models.AbilityAnalysisSourceDataset(
            id="link-1",
            analysis_id=analysis.id,
            job_demand_dataset_id=dataset.id,
            relation_type="primary_evidence",
        )
        session.add(link)
        session.commit()

        result = build_capability_staging(
            session, ref, build_type=BuildType.COMBINED,
        )
        session.commit()
        derived = list(session.scalars(
            select(models.CapabilityGraphStagingEdge).where(
                models.CapabilityGraphStagingEdge.build_id == result.build_id,
                models.CapabilityGraphStagingEdge.edge_type
                == EdgeType.ABILITY_DERIVED_FROM_JOB_REQUIREMENT,
            )
        ))
        assert derived  # at least one ABILITY_DERIVED_* edge

    def test_quality_summary_includes_orphan_nodes_count(
        self, session, sample_combined,
    ):
        ref, _, _ = sample_combined
        result = build_capability_staging(
            session, ref, build_type=BuildType.COMBINED,
        )
        session.commit()
        # Quality summary must surface the orphan count even when zero —
        # downstream consumers can rely on the key being present.
        assert "orphan_nodes_count" in result.quality_summary
        assert "nodes_total" in result.quality_summary
        assert "edges_total" in result.quality_summary

    def test_status_is_generated_after_successful_build(
        self, session, sample_combined,
    ):
        ref, _, _ = sample_combined
        result = build_capability_staging(
            session, ref, build_type=BuildType.COMBINED,
        )
        session.commit()
        build = session.get(
            models.CapabilityGraphStagingBuild, result.build_id,
        )
        assert build.status == BuildStatus.GENERATED
