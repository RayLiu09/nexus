from __future__ import annotations

from fastapi.testclient import TestClient

from nexus_api.api import talent_training_plans
from nexus_api.api import institutional_statistics
from nexus_api.dependencies import Pagination
from nexus_app import models
from nexus_app.enums import AssetKind, AssetVersionStatus, DataSourceType, IngestBatchStatus, NormalizedAssetRefStatus, NormalizedType, RawObjectStatus


PAGE = Pagination(page=1, page_size=20)


def _seed(session, *, suffix: str, status: AssetVersionStatus) -> models.TalentTrainingPlan:
    ds = models.DataSource(id=f"ds-{suffix}", code=f"ds-{suffix}", name="ttp", source_type=DataSourceType.FILE_UPLOAD)
    batch = models.IngestBatch(id=f"batch-{suffix}", data_source_id=ds.id, idempotency_key=f"idem-{suffix}", source_type=DataSourceType.FILE_UPLOAD, status=IngestBatchStatus.COMPLETED)
    raw = models.RawObject(id=f"raw-{suffix}", batch_id=batch.id, data_source_id=ds.id, source_type=DataSourceType.FILE_UPLOAD, object_uri="s3://bucket/raw.pdf", checksum=f"raw-{suffix}", mime_type="application/pdf", status=RawObjectStatus.RAW_PERSISTED)
    asset = models.Asset(id=f"asset-{suffix}", data_source_id=ds.id, source_object_key=f"ttp-{suffix}", title="ttp", asset_kind=AssetKind.DOCUMENT, status=status)
    version = models.AssetVersion(id=f"version-{suffix}", asset_id=asset.id, raw_object_id=raw.id, version_no=1, source_checksum=raw.checksum, version_status=status)
    ref = models.NormalizedAssetRef(id=f"ref-{suffix}", version_id=version.id, normalized_type=NormalizedType.DOCUMENT, object_uri="s3://bucket/normalized.json", schema_version="normalized-document-v1", checksum=f"ref-{suffix}", status=NormalizedAssetRefStatus.GENERATED, governance={}, quality={}, lineage={}, metadata_summary={}, title="跨境电子商务人才培养方案")
    plan = models.TalentTrainingPlan(id=f"ttp-{suffix}", normalized_ref_id=ref.id, asset_version_id=version.id, domain_profile="talent_training_plan.v1", institution_name="杭州万向职业技术学院", major_name="跨境电子商务", major_code="630805", education_level="高职", study_duration="三年", training_goal="培养跨境电商运营人才", training_specification={"ability_requirements":[{"name":"跨境平台操作能力"}]}, career_orientation={"positions":[{"name":"跨境电商B2C运营岗","skills":[{"name":"跨境平台操作能力"}]}]}, certificates=[{"name":"1+X跨境电商运营职业技能等级证书"}], source_title=ref.title, extractor_version="test", evidence={}, quality_flags={}, status="generated")
    course = models.TalentTrainingPlanCourse(id=f"course-{suffix}", plan_id=plan.id, normalized_ref_id=ref.id, item_index=1, course_name="跨境电子商务实务", curriculum_group="professional_core", course_type="course", course_objective="培养跨境平台操作能力", course_content="跨境平台规则与国际物流", skill_refs=[], knowledge_topics=[], evidence={}, metadata_summary={})
    session.add_all([ds, batch, raw, asset, version, ref, plan, course]); session.commit(); return plan


def test_open_query_filters_available_plan_local_json_and_course(session, fake_request):
    available = _seed(session, suffix="available", status=AssetVersionStatus.AVAILABLE)
    _seed(session, suffix="review", status=AssetVersionStatus.REVIEW_REQUIRED)
    response = talent_training_plans._list(fake_request, session, PAGE, True, institution_name=None, major_name=None, major_code="630805", education_level=None, study_duration=None, position="B2C运营", skill="平台操作", certificate="跨境电商运营", course="电子商务实务")
    body = response.model_dump(mode="json")
    assert body["meta"]["total"] == 1
    assert body["data"][0]["id"] == available.id


def test_detail_keeps_plan_local_json_and_course_rows(session):
    plan = _seed(session, suffix="detail", status=AssetVersionStatus.AVAILABLE)
    detail = talent_training_plans._detail(talent_training_plans._get(session, plan.id, True))
    assert detail["career_orientation"]["positions"][0]["name"] == "跨境电商B2C运营岗"
    assert detail["courses"][0]["course_name"] == "跨境电子商务实务"


def test_plan_graph_views_are_deterministic_and_position_graph_is_optional(session):
    plan = _seed(session, suffix="graphs", status=AssetVersionStatus.AVAILABLE)
    course = plan.courses[0]
    course.skill_refs = [{
        "name": "跨境平台操作能力",
        "skill_type": "ability",
        "evidence": {"block_id": "career-table", "page": 3},
    }]
    course.evidence = {"block_id": "curriculum-table", "page": 8}
    plan.career_orientation = {
        "positions": [{
            "name": "跨境电商B2C运营岗",
            "evidence": {"block_id": "career-table", "page": 3},
            "skills": [{
                "name": "跨境平台操作能力",
                "evidence": {"block_id": "career-table", "page": 3},
            }],
        }],
    }
    session.commit()

    course_graph = talent_training_plans._course_knowledge_graph(plan)
    assert course_graph["graph_type"] == "talent_training_plan_course_knowledge.v1"
    assert course_graph["deterministic"] is True
    assert {item["node_type"] for item in course_graph["nodes"]} >= {
        "TalentTrainingPlan", "Course", "Skill",
    }
    assert any(
        edge["relation_type"] == "COURSE_COVERS_SKILL"
        and edge["evidence"]["block_id"] == "career-table"
        for edge in course_graph["edges"]
    )

    position_graph = talent_training_plans._position_capability_graph(plan)
    assert position_graph["available"] is True
    assert any(
        edge["relation_type"] == "POSITION_REQUIRES_SKILL"
        and edge["evidence"]["block_id"] == "career-table"
        for edge in position_graph["edges"]
    )

    plan.career_orientation = {"positions": [{"name": "跨境电商B2C运营岗"}]}
    session.commit()
    unavailable_graph = talent_training_plans._position_capability_graph(plan)
    assert unavailable_graph["available"] is False
    assert unavailable_graph["reason"] == "no_evidenced_position_skill_facts"
    assert unavailable_graph["nodes"] == []
    assert unavailable_graph["edges"] == []


def test_graph_view_routes_return_plan_scoped_projections(app, session):
    plan = _seed(session, suffix="graph-routes", status=AssetVersionStatus.AVAILABLE)
    plan.courses[0].skill_refs = [{"name": "跨境平台操作能力"}]
    session.commit()

    with TestClient(app) as client:
        internal_course = client.get(
            f"/internal/v1/talent-training-plans/{plan.id}/course-knowledge-graph"
        )
        internal_position = client.get(
            f"/internal/v1/talent-training-plans/{plan.id}/position-capability-graph"
        )
        open_course = client.get(
            f"/open/v1/talent-training-plans/{plan.id}/course-knowledge-graph"
        )
        open_position = client.get(
            f"/open/v1/talent-training-plans/{plan.id}/position-capability-graph"
        )

    assert internal_course.status_code == 200
    assert internal_course.json()["data"]["graph_type"] == "talent_training_plan_course_knowledge.v1"
    assert internal_position.status_code == 200
    assert internal_position.json()["data"]["available"] is True
    assert open_course.status_code == 200
    assert open_course.json()["data"]["plan_id"] == plan.id
    assert open_position.status_code == 200
    assert open_position.json()["data"]["available"] is True


def test_province_level_course_and_offering_aggregates(session, fake_request):
    plan = _seed(session, suffix="statistics", status=AssetVersionStatus.AVAILABLE)
    plan.province_name = "浙江省"
    plan.courses[0].course_stat_key = "跨境电子商务实务"
    profile = models.MajorProfile(
        id="mp-statistics",
        normalized_ref_id=plan.normalized_ref_id,
        asset_version_id=plan.asset_version_id,
        domain_profile="major_profile.v1",
        profile_source="institution",
        institution_name=plan.institution_name,
        province_name="浙江省",
        major_name=plan.major_name,
        major_code=plan.major_code,
        education_level=plan.education_level,
        region_tags=["浙江省"],
        source_title=plan.source_title,
        extractor_version="test",
        evidence={}, quality_flags={}, status="generated",
    )
    session.add(profile)
    session.flush()
    session.add(models.MajorProfileCourse(
        id="mp-course-statistics", profile_id=profile.id,
        normalized_ref_id=plan.normalized_ref_id, item_index=1,
        text="不应计入的专业简介课程", source_text="不应计入的专业简介课程",
        evidence_block_ids=[], locator={}, course_group="professional_core",
        course_type="course", course_stat_key="不应计入的专业简介课程",
    ))
    session.commit()

    offerings = institutional_statistics.aggregate_major_offerings(
        fake_request, province_name="浙江省", major_name="跨境电子商务",
        major_code=None, education_level=None, institution_name=None,
        pagination=PAGE, session=session,
    ).model_dump(mode="json")
    courses = institutional_statistics.aggregate_major_courses(
        fake_request, province_name="浙江省", major_name="跨境电子商务",
        major_code=None, education_level=None, institution_name=None,
        course=None, min_coverage_ratio=0.5, pagination=PAGE, session=session,
    ).model_dump(mode="json")

    assert offerings["data"][0]["institution_count"] == 1
    assert courses["data"][0]["course_stat_key"] == "跨境电子商务实务"
    assert courses["data"][0]["coverage_ratio"] == 1.0
    assert all(item["course_stat_key"] != "不应计入的专业简介课程" for item in courses["data"])
    assert courses["aggregations"]["source_policy"] == "combined_prefer_plan"
