"""Public cross-dataset Pipeline-B record and capability-graph API tests."""
from __future__ import annotations

from fastapi.testclient import TestClient

from nexus_app import models
from nexus_app.capability_graph.whitelists import BuildStatus, BuildType, NodeType
from nexus_app.enums import AuditEventType


def _seed_job_record(session, *, record_id: str, dataset_id: str, title: str, company: str, city: str):
    session.add(models.JobDemandDataset(
        id=dataset_id,
        normalized_ref_id=f"ref-{dataset_id}",
        asset_version_id=f"version-{dataset_id}",
        major_name="电子商务",
        industry_name="互联网",
        source_channel="test",
        record_count=1,
        schema_version="job_demand.v1",
        quality_summary={},
    ))
    session.add(models.JobDemandRecord(
        id=record_id,
        dataset_id=dataset_id,
        normalized_ref_id=f"ref-{dataset_id}",
        source_record_key=record_id,
        record_fingerprint=f"fp-{record_id}",
        job_title=title,
        company_name=company,
        city=city,
        education_requirement="本科",
        industry_name="互联网",
        experience_requirement="3-5年",
        quality_flags={},
        trace={},
    ))


def _seed_major_record(session, *, record_id: str, dataset_id: str, province: str, count: int):
    session.add(models.MajorDistributionDataset(
        id=dataset_id,
        normalized_ref_id=f"ref-{dataset_id}",
        asset_version_id=f"version-{dataset_id}",
        dataset_name=dataset_id,
        source_channel="test",
        major_scope="电子商务",
        record_count=1,
        province_count=1,
        schema_version="major_distribution.v1",
        quality_summary={},
    ))
    session.add(models.MajorDistributionRecord(
        id=record_id,
        dataset_id=dataset_id,
        normalized_ref_id=f"ref-{dataset_id}",
        source_record_key=record_id,
        year=2025,
        province_name=province,
        region_scope="省",
        major_name="电子商务",
        major_code="530701",
        distribution_count=count,
        quality_flags={},
        trace={},
    ))


def _seed_build(session, *, build_id: str, build_type: str, major_name: str | None = "电子商务"):
    session.add(models.CapabilityGraphStagingBuild(
        id=build_id,
        normalized_ref_id=f"ref-{build_id}",
        domain="test",
        build_type=build_type,
        status=BuildStatus.GENERATED,
        schema_version="capability_graph_staging.v1",
        quality_summary={},
        major_name=major_name,
        major_code="530701" if major_name else None,
    ))


def _seed_node(session, *, node_id: str, build_id: str, node_type: str, name: str):
    session.add(models.CapabilityGraphStagingNode(
        id=node_id,
        build_id=build_id,
        node_type=node_type,
        node_key=node_id,
        display_name=name,
        properties={},
    ))


def test_open_job_demand_records_are_cross_dataset_and_ignore_version_status(app, session):
    _seed_job_record(session, record_id="job-1", dataset_id="job-dataset-1", title="数据分析师", company="甲公司", city="杭州")
    _seed_job_record(session, record_id="job-2", dataset_id="job-dataset-2", title="数据分析师", company="乙公司", city="杭州")
    session.commit()

    with TestClient(app) as client:
        result = client.get("/open/v1/record-assets/job-demand-records", params={
            "job_title": "数据分析", "city": "杭州", "education": "本科", "experience": "3-5",
        })
        obsolete = client.get("/open/v1/record-assets/job-demand-datasets/job-dataset-1/records")

    assert result.status_code == 200
    assert result.json()["meta"]["total"] == 2
    assert {item["dataset_id"] for item in result.json()["data"]} == {"job-dataset-1", "job-dataset-2"}
    assert obsolete.status_code == 404
    assert session.query(models.AuditLog).filter(
        models.AuditLog.event_type == AuditEventType.OPEN_RECORD_ASSETS_ACCESSED
    ).count() == 1


def test_open_major_distribution_aggregate_is_cross_dataset(app, session):
    _seed_major_record(session, record_id="major-1", dataset_id="major-dataset-1", province="浙江省", count=10)
    _seed_major_record(session, record_id="major-2", dataset_id="major-dataset-2", province="浙江省", count=20)
    session.commit()

    with TestClient(app) as client:
        result = client.get("/open/v1/record-assets/major-distribution-records/aggregate", params={
            "year": 2025, "province_name": "浙江", "major_code": "530701", "group_by": "province_name",
        })

    assert result.status_code == 200
    assert result.json()["meta"]["total"] == 1
    assert result.json()["data"] == [{"province_name": "浙江省", "distribution_total": 30, "record_count": 2}]


def test_open_graph_adapters_only_return_generated_graphs(app, session):
    _seed_build(session, build_id="ability-build", build_type=BuildType.ABILITY_ANALYSIS)
    _seed_build(session, build_id="teaching-build", build_type=BuildType.TEACHING_STANDARD)
    _seed_build(session, build_id="job-build", build_type=BuildType.JOB_DEMAND, major_name=None)
    _seed_node(session, node_id="ability-node", build_id="ability-build", node_type="Ability", name="运营能力")
    _seed_node(session, node_id="teaching-node", build_id="teaching-build", node_type="Major", name="电子商务")
    _seed_node(session, node_id="role-node", build_id="job-build", node_type=NodeType.JOB_ROLE, name="数据分析师")
    session.commit()

    with TestClient(app) as client:
        ability = client.get("/open/v1/record-assets/graphs/occupational-capability", params={"major_code": "530701"})
        teaching = client.get("/open/v1/record-assets/graphs/teaching-standard-knowledge", params={"major_name": "电子商务"})
        job = client.get("/open/v1/record-assets/graphs/job-capability", params={"job_title": "数据分析"})

    assert ability.status_code == teaching.status_code == job.status_code == 200
    assert ability.json()["data"]["build"]["id"] == "ability-build"
    assert teaching.json()["data"]["build"]["id"] == "teaching-build"
    assert job.json()["data"]["builds"][0]["id"] == "job-build"
