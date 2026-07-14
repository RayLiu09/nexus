"""B8.2 — CapabilityGraphStaging builders + service.

Coverage:
- Whitelist constants stay aligned with the contract (NODE_TYPES,
  EDGE_TYPES, BuildType / BuildStatus) — a regression here would mean
  the design and code drifted.
- `NodeSpec` / `EdgeSpec` validators reject bad input fast (off-whitelist
  node_type, empty keys, malformed edge endpoints).
- `build_job_demand` builder produces the expected node + edge shape
  (record + role aggregation + skill / literacy dedup).
- `build_ability_analysis` builder mirrors the persisted task → wc →
  ability tree and respects the G/S/D no-work-content rule.
- `combined_ability_derived_edges` emits cross-domain ABILITY_DERIVED_*
  edges when an ability_analysis_source_dataset link exists.
- `build_capability_staging` (service) end-to-end:
  - persists build + nodes + edges, returns matching counts
  - dedups duplicate nodes / drops dangling-endpoint edges
  - emits `quality_summary` with the contract keys
  - skips cleanly for unsupported build_type / empty domain data
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from nexus_app import models
from nexus_app.capability_graph import (
    BUILD_TYPES,
    EDGE_TYPES,
    NODE_TYPES,
    STAGING_SCHEMA_VERSION,
    BuildResult,
    EdgeSpec,
    NodeSpec,
    build_capability_staging,
)
from nexus_app.capability_graph.builders import (
    build_ability_analysis,
    build_job_demand,
    combined_ability_derived_edges,
)
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


# ---------------------------------------------------------------------------
# Whitelist + spec validation
# ---------------------------------------------------------------------------


class TestWhitelists:
    def test_node_types_include_all_design_section_7_3(self):
        # CourseModule reserved but present in the whitelist.
        assert {
            "JobRole", "JobDemandRecord", "Skill", "ProfessionalLiteracy",
            "WorkTask", "WorkContent", "Ability", "CourseModule",
        } <= NODE_TYPES

    def test_edge_types_include_all_design_section_7_4(self):
        assert {
            "JOB_RECORD_HAS_SKILL", "JOB_RECORD_HAS_LITERACY",
            "JOB_RECORD_HAS_WORK_CONTENT",
            "JOB_ROLE_AGGREGATES_RECORD", "JOB_ROLE_REQUIRES_SKILL",
            "JOB_ROLE_REQUIRES_LITERACY", "JOB_ROLE_REQUIRES_WORK_CONTENT",
            "TASK_HAS_WORK_CONTENT",
            "TASK_REQUIRES_ABILITY", "WORK_CONTENT_REQUIRES_ABILITY",
            "ABILITY_MAPS_TO_SKILL",
            "ABILITY_DERIVED_FROM_JOB_REQUIREMENT",
            "SKILL_COVERED_BY_COURSE_MODULE",
            "ABILITY_COVERED_BY_COURSE_MODULE",
        } <= EDGE_TYPES

    def test_build_types_canonical(self):
        assert BUILD_TYPES == {
            "job_demand", "ability_analysis", "combined", "teaching_standard",
        }


class TestSpecValidation:
    def test_node_rejects_off_whitelist_type(self):
        with pytest.raises(ValueError, match="NODE_TYPES whitelist"):
            NodeSpec(node_type="Garbage", node_key="x", display_name="x")

    def test_node_rejects_empty_key(self):
        with pytest.raises(ValueError, match="node_key"):
            NodeSpec(node_type=NodeType.SKILL, node_key="", display_name="x")

    def test_node_rejects_empty_display_name(self):
        with pytest.raises(ValueError, match="display_name"):
            NodeSpec(node_type=NodeType.SKILL, node_key="k", display_name="")

    def test_edge_rejects_off_whitelist_type(self):
        with pytest.raises(ValueError, match="EDGE_TYPES whitelist"):
            EdgeSpec(
                edge_type="NOPE",
                source_node_key=(NodeType.SKILL, "k1"),
                target_node_key=(NodeType.SKILL, "k2"),
            )

    def test_edge_rejects_malformed_endpoints(self):
        with pytest.raises(ValueError, match="source_node_key"):
            EdgeSpec(
                edge_type=EdgeType.JOB_RECORD_HAS_SKILL,
                source_node_key=("not-a-tuple-of-2",),  # type: ignore[arg-type]
                target_node_key=(NodeType.SKILL, "k"),
            )


# ---------------------------------------------------------------------------
# Synthetic data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def normalized_ref(session):
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
    session.add_all([asset, raw, version, ref])
    session.commit()
    return ref


@pytest.fixture
def job_demand_seed(session, normalized_ref):
    dataset = models.JobDemandDataset(
        id="ds", normalized_ref_id=normalized_ref.id, asset_version_id="v",
        source_channel="excel_upload", record_count=2,
        schema_version="job_demand.v1",
    )
    session.add(dataset)
    session.flush()
    records = [
        models.JobDemandRecord(
            id="rec-1", dataset_id="ds", normalized_ref_id=normalized_ref.id,
            source_record_key="r1", job_title="数据分析师",
            company_name="字节", city="北京",
            record_fingerprint="fp1",
        ),
        models.JobDemandRecord(
            id="rec-2", dataset_id="ds", normalized_ref_id=normalized_ref.id,
            source_record_key="r2", job_title="数据分析师",  # same role
            company_name="美团", city="上海",
            record_fingerprint="fp2",
        ),
    ]
    session.add_all(records)
    session.flush()
    items = [
        models.JobDemandRequirementItem(
            id="item-1", record_id="rec-1", dataset_id="ds",
            item_type="professional_skill", item_name="Python",
            normalized_name="python", confidence=Decimal("0.90"),
        ),
        models.JobDemandRequirementItem(
            id="item-2", record_id="rec-2", dataset_id="ds",
            item_type="professional_skill", item_name="Python",  # dup → 1 Skill
            normalized_name="python", confidence=Decimal("0.88"),
        ),
        models.JobDemandRequirementItem(
            id="item-3", record_id="rec-1", dataset_id="ds",
            item_type="professional_literacy", item_name="团队协作",
            confidence=Decimal("0.85"),
        ),
        models.JobDemandRequirementItem(
            id="item-4", record_id="rec-1", dataset_id="ds",
            item_type="tool", item_name="SQL",
            normalized_name="sql", confidence=Decimal("0.91"),
        ),
        models.JobDemandRequirementItem(
            id="item-5", record_id="rec-2", dataset_id="ds",
            item_type="certificate", item_name="数据分析师证书",
            normalized_name="数据分析师证书", confidence=Decimal("0.86"),
        ),
        models.JobDemandRequirementItem(
            id="item-6", record_id="rec-2", dataset_id="ds",
            item_type="work_task_candidate", item_name="经营数据看板维护",
            normalized_name="经营数据看板维护", confidence=Decimal("0.82"),
        ),
    ]
    session.add_all(items)
    session.commit()
    return dataset, records, items


@pytest.fixture
def ability_seed(session, normalized_ref):
    profile = models.AbilityAnalysisProfile(
        id="prof-pgsd", model_code="PGSD", model_name="PGSD",
        schema_version="ability_analysis.pgsd.v1",
        category_schema=[{"code": "P"}, {"code": "G"}],
        code_pattern={
            "P": {"regex": r"^P-\d+\.\d+\.\d+$", "segments": 3, "requires_work_content": True},
            "G": {"regex": r"^G-\d+\.\d+$", "segments": 2, "requires_work_content": False},
        },
        is_active=True, is_builtin=True,
    )
    analysis = models.OccupationalAbilityAnalysis(
        id="ana", normalized_ref_id=normalized_ref.id, asset_version_id="v",
        profile_id="prof-pgsd", analysis_model="PGSD",
        schema_version="ability_analysis.pgsd.v1",
    )
    session.add_all([profile, analysis])
    session.flush()
    task = models.OccupationalWorkTask(
        id="t", analysis_id="ana", task_code="1", task_name="数据采集",
        task_description="x", task_description_structured={}, display_order=1,
    )
    wc = models.OccupationalWorkContent(
        id="wc", analysis_id="ana", task_id="t",
        content_code="1.1", content_name="日志采集",
        content_description="采集日志系统数据",
        display_order=1,
    )
    session.add_all([task, wc])
    session.flush()
    abilities = [
        models.OccupationalAbilityItem(
            id="ab-p", analysis_id="ana", task_id="t", work_content_id="wc",
            ability_code="P-1.1.1", ability_major_category_code="P",
            ability_major_category_name="职业能力",
            ability_sequence="1.1.1",
            ability_content="能用工具采集日志数据",
            confidence=Decimal("0.92"),
        ),
        models.OccupationalAbilityItem(
            id="ab-g", analysis_id="ana", task_id="t", work_content_id=None,
            ability_code="G-1.1", ability_major_category_code="G",
            ability_major_category_name="通用能力",
            ability_sequence="1.1",
            ability_content="团队协作能力",
        ),
    ]
    session.add_all(abilities)
    session.commit()
    return analysis, task, wc, abilities


# ---------------------------------------------------------------------------
# Builder unit tests
# ---------------------------------------------------------------------------


class TestBuildJobDemand:
    def test_record_and_role_nodes_created(self, session, job_demand_seed):
        dataset, records, items = job_demand_seed
        nodes, edges = build_job_demand(
            dataset=dataset, records=records, requirement_items=items,
        )
        node_types = [n.node_type for n in nodes]
        # 2 JobDemandRecord + 1 JobRole (dedup on title) + 3 Skill
        # (professional_skill dedup + tool + certificate) + 1 Literacy + 1 WorkContent.
        assert node_types.count(NodeType.JOB_DEMAND_RECORD) == 2
        assert node_types.count(NodeType.JOB_ROLE) == 1
        assert node_types.count(NodeType.SKILL) == 3
        assert node_types.count(NodeType.PROFESSIONAL_LITERACY) == 1
        assert node_types.count(NodeType.WORK_CONTENT) == 1

        skill_nodes = [node for node in nodes if node.node_type == NodeType.SKILL]
        assert {node.properties.get("item_type") for node in skill_nodes} == {
            "professional_skill", "tool", "certificate",
        }

    def test_edges_include_role_aggregation_and_skill_links(
        self, session, job_demand_seed,
    ):
        dataset, records, items = job_demand_seed
        _, edges = build_job_demand(
            dataset=dataset, records=records, requirement_items=items,
        )
        types = [e.edge_type for e in edges]
        # 2 records → 2 JOB_ROLE_AGGREGATES_RECORD
        assert types.count(EdgeType.JOB_ROLE_AGGREGATES_RECORD) == 2
        # 4 skill-like items (professional_skill/tool/certificate)
        # → 4 HAS + 4 REQUIRES.
        assert types.count(EdgeType.JOB_RECORD_HAS_SKILL) == 4
        assert types.count(EdgeType.JOB_ROLE_REQUIRES_SKILL) == 4
        # 1 literacy item → 1 HAS + 1 REQUIRES
        assert types.count(EdgeType.JOB_RECORD_HAS_LITERACY) == 1
        assert types.count(EdgeType.JOB_ROLE_REQUIRES_LITERACY) == 1
        # 1 work_task_candidate item → WorkContent edges, not literacy edges.
        assert types.count(EdgeType.JOB_RECORD_HAS_WORK_CONTENT) == 1
        assert types.count(EdgeType.JOB_ROLE_REQUIRES_WORK_CONTENT) == 1


class TestBuildAbilityAnalysis:
    def test_task_wc_ability_nodes_created(self, session, ability_seed):
        analysis, tasks, wcs, abilities = ability_seed
        nodes, edges = build_ability_analysis(
            analysis=analysis, tasks=[tasks], work_contents=[wcs],
            abilities=abilities,
        )
        node_types = [n.node_type for n in nodes]
        assert NodeType.WORK_TASK in node_types
        assert NodeType.WORK_CONTENT in node_types
        assert node_types.count(NodeType.ABILITY) == 2
        wc_node = next(n for n in nodes if n.node_type == NodeType.WORK_CONTENT)
        assert wc_node.display_name == "采集日志系统数据"
        assert wc_node.properties["content_code"] == "1.1"
        assert wc_node.properties["content_name"] == "日志采集"
        assert wc_node.properties["content_description"] == "采集日志系统数据"

    def test_p_ability_gets_work_content_edge(self, session, ability_seed):
        analysis, t, wc, abilities = ability_seed
        _, edges = build_ability_analysis(
            analysis=analysis, tasks=[t], work_contents=[wc],
            abilities=abilities,
        )
        types = [e.edge_type for e in edges]
        assert EdgeType.TASK_HAS_WORK_CONTENT in types
        # P is linked through work_content; G hangs directly on task.
        assert types.count(EdgeType.WORK_CONTENT_REQUIRES_ABILITY) == 1
        assert types.count(EdgeType.TASK_REQUIRES_ABILITY) == 1


class TestCombinedDerivedEdges:
    def test_emits_one_edge_per_ability_per_record_when_link_present(self):
        link = type("L", (), {"id": "link-1"})()
        ability = type("A", (), {"ability_code": "P-1.1.1"})()
        record = type("R", (), {"id": "rec-1"})()
        edges = combined_ability_derived_edges(
            source_dataset_links=[link],   # type: ignore[arg-type]
            abilities=[ability],            # type: ignore[arg-type]
            job_demand_records=[record],    # type: ignore[arg-type]
        )
        assert len(edges) == 1
        assert edges[0].edge_type == EdgeType.ABILITY_DERIVED_FROM_JOB_REQUIREMENT

    def test_empty_when_no_link(self):
        ability = type("A", (), {"ability_code": "P-1.1.1"})()
        record = type("R", (), {"id": "rec-1"})()
        assert combined_ability_derived_edges(
            source_dataset_links=[],
            abilities=[ability],            # type: ignore[arg-type]
            job_demand_records=[record],    # type: ignore[arg-type]
        ) == []


# ---------------------------------------------------------------------------
# Service end-to-end
# ---------------------------------------------------------------------------


class TestServiceOrchestrator:
    def test_job_demand_build_persists_rows(
        self, session, normalized_ref, job_demand_seed,
    ):
        result = build_capability_staging(
            session, normalized_ref, build_type=BuildType.JOB_DEMAND,
        )
        session.commit()
        assert result.skipped is False
        assert result.build_id
        assert result.nodes_written > 0
        assert result.edges_written > 0

        build = session.get(models.CapabilityGraphStagingBuild, result.build_id)
        assert build is not None
        assert build.status == BuildStatus.GENERATED
        assert build.schema_version == STAGING_SCHEMA_VERSION
        assert build.quality_summary["nodes_total"] == result.nodes_written
        assert build.quality_summary["edges_total"] == result.edges_written

        # Sanity: actual DB row counts agree with the result.
        node_count = session.scalar(
            select(models.CapabilityGraphStagingNode).where(
                models.CapabilityGraphStagingNode.build_id == build.id
            ).with_only_columns(models.CapabilityGraphStagingNode.id).count()
        ) if False else None  # SQL count avoided — use scalar(len()) below
        nodes = list(session.scalars(
            select(models.CapabilityGraphStagingNode).where(
                models.CapabilityGraphStagingNode.build_id == build.id
            )
        ))
        assert len(nodes) == result.nodes_written

    def test_ability_analysis_build_persists_rows(
        self, session, normalized_ref, ability_seed,
    ):
        result = build_capability_staging(
            session, normalized_ref, build_type=BuildType.ABILITY_ANALYSIS,
        )
        session.commit()
        assert result.skipped is False
        assert result.nodes_written >= 4  # 1 task + 1 wc + 2 abilities
        edges = list(session.scalars(
            select(models.CapabilityGraphStagingEdge).where(
                models.CapabilityGraphStagingEdge.build_id == result.build_id
            )
        ))
        edge_types = {e.edge_type for e in edges}
        assert EdgeType.TASK_HAS_WORK_CONTENT in edge_types
        assert EdgeType.WORK_CONTENT_REQUIRES_ABILITY in edge_types
        assert EdgeType.TASK_REQUIRES_ABILITY in edge_types

    def test_combined_build_covers_both_domains(
        self, session, normalized_ref, job_demand_seed, ability_seed,
    ):
        result = build_capability_staging(
            session, normalized_ref, build_type=BuildType.COMBINED,
        )
        session.commit()
        nodes = list(session.scalars(
            select(models.CapabilityGraphStagingNode).where(
                models.CapabilityGraphStagingNode.build_id == result.build_id
            )
        ))
        types = {n.node_type for n in nodes}
        # Both domains' node types present.
        assert NodeType.JOB_DEMAND_RECORD in types
        assert NodeType.WORK_TASK in types
        assert NodeType.SKILL in types
        assert NodeType.ABILITY in types

    def test_combined_build_emits_derived_edge_when_link_exists(
        self, session, normalized_ref, job_demand_seed, ability_seed,
    ):
        dataset = job_demand_seed[0]
        analysis = ability_seed[0]
        link = models.AbilityAnalysisSourceDataset(
            id="link-1",
            analysis_id=analysis.id,
            job_demand_dataset_id=dataset.id,
            relation_type="primary_evidence",
        )
        session.add(link)
        session.commit()

        result = build_capability_staging(
            session, normalized_ref, build_type=BuildType.COMBINED,
        )
        session.commit()
        edges = list(session.scalars(
            select(models.CapabilityGraphStagingEdge).where(
                models.CapabilityGraphStagingEdge.build_id == result.build_id,
                models.CapabilityGraphStagingEdge.edge_type
                == EdgeType.ABILITY_DERIVED_FROM_JOB_REQUIREMENT,
            )
        ))
        assert edges  # at least one derived edge present

    def test_unsupported_build_type_skips(self, session, normalized_ref):
        result = build_capability_staging(
            session, normalized_ref, build_type="nonsense",
        )
        assert result.skipped is True
        assert result.skipped_reason == "unsupported_build_type"

    def test_no_domain_data_skips(self, session, normalized_ref):
        # No dataset / analysis seeded under this normalized_ref → skip.
        result = build_capability_staging(
            session, normalized_ref, build_type=BuildType.JOB_DEMAND,
        )
        assert result.skipped is True
        assert result.skipped_reason == "no_domain_data"

    def test_quality_summary_does_not_count_gsd_task_abilities_as_orphans(
        self, session, normalized_ref, ability_seed,
    ):
        result = build_capability_staging(
            session, normalized_ref, build_type=BuildType.ABILITY_ANALYSIS,
        )
        session.commit()
        assert "orphan_nodes_count" in result.quality_summary
        assert result.quality_summary["orphan_nodes_count"] == 0
