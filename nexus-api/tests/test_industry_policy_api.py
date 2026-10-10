from fastapi.testclient import TestClient

from nexus_app import models
from nexus_app.enums import TagAssetIndexSource, TagAssetIndexTargetType

from tests.test_asset_catalog_api import _seed_review_required_asset


def test_industry_policy_list_is_available_without_pipeline_specific_tables(app):
    response = TestClient(app).get("/internal/v1/industry-policies")

    assert response.status_code == 200
    assert response.json()["data"] == []
    assert response.json()["meta"]["total"] == 0


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
        "region": [],
        "industry": ["低空经济"],
        "publish_date": "2025-07-01",
        "content_tags": ["市场规模"],
    }]
