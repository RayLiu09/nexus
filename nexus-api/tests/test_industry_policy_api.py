from fastapi.testclient import TestClient

from nexus_api.dependencies import require_user
from nexus_app import models
from nexus_app.enums import AuditEventType, TagAssetIndexSource, TagAssetIndexTargetType, UserRole

from tests.test_asset_catalog_api import _seed_review_required_asset


def test_industry_policy_list_is_available_without_pipeline_specific_tables(app):
    response = TestClient(app).get("/internal/v1/industry-policies")

    assert response.status_code == 200
    assert response.json()["data"] == []
    assert response.json()["meta"]["total"] == 0


def test_talent_demand_report_list_reads_document_identity_without_domain_table(app, session):
    seeded = _seed_review_required_asset(session)
    seeded["result"].classification = "talent_demand_report"
    seeded["ref"].document_metadata = {
        "talent_demand_report": {
            "major_name": "大数据技术（含地理信息应用方向）",
            "major_code": "510205",
            "institution_name": None,
        }
    }
    session.add(models.TagAssetIndex(
        tag_type="topic", tag_value="岗位需求", tag_value_normalized="岗位需求",
        target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
        target_id=seeded["ref"].id,
        asset_version_id=seeded["version"].id,
        source=TagAssetIndexSource.GOVERNANCE_TAG,
    ))
    session.commit()

    response = TestClient(app).get("/internal/v1/talent-demand-reports")
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["major_name"] == "大数据技术（含地理信息应用方向）"
    assert body["data"][0]["major_code"] == "510205"
    assert body["data"][0]["institution_name"] is None
    assert body["data"][0]["content_tags"] == ["岗位需求"]


def test_teaching_case_list_uses_content_title_and_current_governed_tags(app, session):
    seeded = _seed_review_required_asset(session)
    seeded["result"].classification = "teaching_case"
    seeded["ref"].document_metadata = {"title": "教学案例——智慧家居电商运营数据处理"}
    session.add(models.TagAssetIndex(
        tag_type="topic", tag_value="电商运营", tag_value_normalized="电商运营",
        target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
        target_id=seeded["ref"].id,
        asset_version_id=seeded["version"].id,
        source=TagAssetIndexSource.GOVERNANCE_TAG,
    ))
    session.commit()

    client = TestClient(app)
    body = client.get("/internal/v1/teaching-cases").json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["asset_name"] == "智慧家居电商运营数据处理"
    assert body["data"][0]["content_tags"] == ["电商运营"]
    assert body["data"][0]["normalized_ref_id"] == seeded["ref"].id
    assert body["data"][0]["raw_object_id"] == seeded["version"].raw_object_id
    assert client.get("/internal/v1/asset-center/counts").json()["data"]["counts"]["teaching-resources/cases"] == 1
    seeded["result"].classification = "course_textbook"
    session.commit()
    assert client.get("/internal/v1/teaching-cases").json()["meta"]["total"] == 0


def test_business_expert_can_fill_report_identity_with_audit_and_repeat_is_idempotent(app, session, stub_user):
    seeded = _seed_review_required_asset(session)
    seeded["result"].classification = "talent_demand_report"
    seeded["ref"].document_metadata = {"talent_demand_report": {
        "major_name": "大数据与会计", "major_code": None, "institution_name": None,
        "evidence": {"major_name_block_id": "cover"},
    }}
    session.commit()
    stub_user.role = UserRole.BUSINESS_EXPERT
    url = f"/internal/v1/talent-demand-reports/{seeded['asset'].id}/identity"
    payload = {
        "normalized_ref_id": seeded["ref"].id,
        "major_code": "530302",
        "institution_name": "测试职业学院",
    }
    client = TestClient(app)
    first = client.patch(url, json=payload)
    assert first.status_code == 200
    assert first.json()["data"]["major_code"] == "530302"
    assert client.patch(url, json=payload).status_code == 200
    audit = session.query(models.AuditLog).filter_by(
        event_type=AuditEventType.TALENT_DEMAND_REPORT_IDENTITY_UPDATED,
    ).all()
    assert len(audit) == 1
    assert audit[0].actor_id == stub_user.id
    assert audit[0].summary["before"]["major_code"] is None
    assert audit[0].summary["after"]["major_code"] == "530302"
    assert seeded["ref"].document_metadata["talent_demand_report"]["major_code"] is None
    listing = client.get("/internal/v1/talent-demand-reports").json()["data"][0]
    assert listing["major_code"] == "530302"
    assert listing["institution_name"] == "测试职业学院"


def test_only_business_expert_can_edit_current_report_ref(app, session, stub_user):
    seeded = _seed_review_required_asset(session)
    seeded["result"].classification = "talent_demand_report"
    session.commit()
    url = f"/internal/v1/talent-demand-reports/{seeded['asset'].id}/identity"
    client = TestClient(app)
    body = {"normalized_ref_id": seeded["ref"].id, "major_code": "510205"}
    assert client.patch(url, json=body).status_code == 403
    stub_user.role = UserRole.BUSINESS_EXPERT
    assert client.patch(url, json={**body, "normalized_ref_id": "stale-ref"}).status_code == 409
    assert client.patch(url, json={**body, "major_code": "invalid"}).status_code == 422
    assert client.patch(url, json={**body, "unknown": "value"}).status_code == 422
    seeded["result"].classification = "industry_report"
    session.commit()
    assert client.patch(url, json=body).status_code == 409
    assert session.query(models.AuditLog).filter_by(
        event_type=AuditEventType.TALENT_DEMAND_REPORT_IDENTITY_UPDATED,
    ).count() == 0


def test_industry_policy_list_reads_official_classification_and_typed_metadata(app, session):
    seeded = _seed_review_required_asset(session)
    seeded["result"].classification = "industry_policy"
    seeded["ref"].document_metadata = {"publish_date": "2025-06-18"}
    for tag_type, value in (
        ("region", "浙江省"),
        ("region", "杭州市"),
        ("industry", "跨境电商"),
        ("topic", "产业扶持"),
    ):
        session.add(models.TagAssetIndex(
            tag_type=tag_type,
            tag_value=value,
            tag_value_normalized=value,
            target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
            target_id=seeded["ref"].id,
            asset_version_id=seeded["version"].id,
            source=TagAssetIndexSource.GOVERNANCE_TAG,
        ))
    session.commit()

    response = TestClient(app).get("/internal/v1/industry-policies")

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 1
    assert body["data"] == [
        {
            "id": seeded["asset"].id,
            "asset_name": seeded["asset"].title,
            "normalized_ref_id": seeded["ref"].id,
            "raw_object_id": seeded["version"].raw_object_id,
            "region": ["杭州市", "浙江省"],
            "industry": ["跨境电商"],
            "publish_date": "2025-06-18",
            "content_tags": ["产业扶持"],
        }
    ]


def test_sector_report_list_maps_report_fields_and_excludes_other_reports(app, session):
    seeded = _seed_review_required_asset(session)
    seeded["result"].classification = "sector_report"
    seeded["ref"].document_metadata = {"publish_date": "2025-07-01"}
    for tag_type, value in (
        ("industry", "低空经济"),
        ("topic", "市场规模"),
    ):
        session.add(models.TagAssetIndex(
            tag_type=tag_type,
            tag_value=value,
            tag_value_normalized=value,
            target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
            target_id=seeded["ref"].id,
            asset_version_id=seeded["version"].id,
            source=TagAssetIndexSource.GOVERNANCE_TAG,
        ))
    other = _seed_review_required_asset(session, suffix="industry-report")
    other["result"].classification = "industry_report"
    session.commit()

    response = TestClient(app).get("/internal/v1/sector-reports")

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 1
    assert body["data"] == [{
        "id": seeded["asset"].id,
        "asset_name": seeded["asset"].title,
        "normalized_ref_id": seeded["ref"].id,
        "raw_object_id": seeded["version"].raw_object_id,
        "region": [],
        "industry": ["低空经济"],
        "publish_date": "2025-07-01",
        "content_tags": ["市场规模"],
    }]


def test_document_topic_filters_count_full_list_and_keep_overlapping_assets(app, session):
    assets = {}
    for suffix, classification, title, industry in (
        ("finance", "industry_policy", "跨境电商行动方案", "电子商务"),
        ("low-altitude", "industry_policy", "低空经济行动方案", "低空经济"),
        ("both", "industry_policy", "低空物流行动方案", "低空经济"),
        ("other", "industry_policy", "职业教育行动方案", "职业教育"),
        ("report", "industry_report", "低空经济报告", "低空经济"),
    ):
        seeded = _seed_review_required_asset(session, suffix=suffix)
        seeded["asset"].title = title
        seeded["result"].classification = classification
        session.add(models.TagAssetIndex(
            tag_type="industry",
            tag_value=industry,
            tag_value_normalized=industry,
            target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
            target_id=seeded["ref"].id,
            asset_version_id=seeded["version"].id,
            source=TagAssetIndexSource.GOVERNANCE_TAG,
        ))
        assets[suffix] = seeded["asset"].id
    session.commit()

    client = TestClient(app)
    base = "/internal/v1/industry-policies"
    assert client.get(base).json()["meta"]["total"] == 4
    finance = client.get(base, params={"topic": "finance_commerce", "pageSize": 1}).json()
    low_altitude = client.get(base, params={"topic": "low_altitude", "pageSize": 1}).json()
    assert finance["meta"]["total"] == 2
    assert low_altitude["meta"]["total"] == 2
    assert len(finance["data"]) == len(low_altitude["data"]) == 1
    assert assets["both"] in {
        row["id"] for page in (1, 2)
        for row in client.get(base, params={"topic": "finance_commerce", "page": page, "pageSize": 1}).json()["data"]
    }
    assert client.get("/internal/v1/industry-reports", params={"topic": "low_altitude"}).json()["meta"]["total"] == 1
    assert client.get(base, params={"topic": "unknown"}).status_code == 422
