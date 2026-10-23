"""Console document filters operate on the catalog-selected official tags."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from nexus_app import models
from nexus_app.enums import TagAssetIndexSource, TagAssetIndexTargetType
from tests.test_asset_catalog_api import _seed_review_required_asset


DOCUMENT_ROUTES = [
    ("industry-policies", "industry_policy"),
    ("industry-reports", "industry_report"),
    ("sector-reports", "sector_report"),
    ("major-profile-documents", "major_profile"),
    ("talent-demand-reports", "talent_demand_report"),
    ("teaching-cases", "teaching_case"),
]


def add_tag(session, seeded, tag_type, value, *, ref_id=None):
    session.add(models.TagAssetIndex(
        tag_type=tag_type, tag_value=value, tag_value_normalized=value.lower(),
        target_type=TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
        target_id=ref_id or seeded["ref"].id,
        asset_version_id=seeded["version"].id,
        source=TagAssetIndexSource.GOVERNANCE_TAG,
    ))


@pytest.mark.parametrize("route,classification", DOCUMENT_ROUTES)
def test_document_filters_intersect_before_count_and_page(app, session, route, classification):
    selected = []
    for index, region in enumerate(["重庆市", "重庆市", "成都市"]):
        seeded = _seed_review_required_asset(session, suffix=f"filter-{index}")
        seeded["result"].classification = classification
        for tag_type, value in [("region", region), ("industry", "电子商务"), ("topic", "跨境电商")]:
            add_tag(session, seeded, tag_type, value)
        if region == "重庆市":
            selected.append(seeded["asset"].id)
    session.commit()
    client = TestClient(app)
    url = f"/internal/v1/{route}"
    filters = {"region": " 重庆 ", "industry": "商务", "content_tag": "跨境", "pageSize": 1}
    first = client.get(url, params=filters)
    assert first.status_code == 200, first.text
    second = client.get(url, params={**filters, "page": 2}).json()
    assert first.json()["meta"]["total"] == second["meta"]["total"] == 2
    assert {first.json()["data"][0]["id"], second["data"][0]["id"]} == set(selected)
    assert client.get(url, params={**filters, "industry": "航空"}).json()["meta"]["total"] == 0
    assert client.get(url, params={"region": "  ", "industry": "", "content_tag": " "}).json()["meta"]["total"] == 3
    assert client.get(url, params={"content_tag": "重庆"}).json()["meta"]["total"] == 0
    for field in ["region", "industry", "content_tag"]:
        assert client.get(url, params={field: "x" * 129}).status_code == 422


def test_content_filter_uses_latest_official_fallback_and_index_precedence(app, session):
    fallback = _seed_review_required_asset(session, suffix="fallback")
    fallback["result"].tags = ["旧标签"]
    # Only typed region/industry rows still permit the displayed content fallback.
    add_tag(session, fallback, "region", "成都市")
    session.add(models.GovernanceResult(
        normalized_ref_id=fallback["ref"].id, classification="industry_report", level="L1",
        tags=["产教融合"], index_admission=False, status=fallback["result"].status,
        # SQLite returns persisted timestamps without tzinfo; keep the
        # explicit ordering comparable to the seeded row in both backends.
        created_at=fallback["result"].created_at.replace(tzinfo=None) + timedelta(seconds=1),
    ))
    indexed = _seed_review_required_asset(session, suffix="indexed")
    indexed["result"].tags = ["产教融合"]
    add_tag(session, indexed, "topic", "数字经济")
    session.commit()
    # Force both results through the SQLite adapter so their timezone shape is
    # identical to the PostgreSQL-loaded values used by the catalog resolver.
    session.expire_all()
    client = TestClient(app)
    url = "/internal/v1/industry-reports"
    body = client.get(url, params={"content_tag": "融合", "region": "成都"}).json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["id"] == fallback["asset"].id
    assert body["data"][0]["content_tags"] == ["产教融合"]
    assert client.get(url, params={"content_tag": "旧标签"}).json()["meta"]["total"] == 0
    body = client.get(url, params={"content_tag": "融合"}).json()
    assert [row["id"] for row in body["data"]] == [fallback["asset"].id]
    body = client.get(url, params={"content_tag": "数字"}).json()
    assert [row["id"] for row in body["data"]] == [indexed["asset"].id]


def test_filters_are_literal_case_insensitive_and_ignore_other_refs(app, session):
    seeded = _seed_review_required_asset(session, suffix="literal")
    add_tag(session, seeded, "industry", "Retail_100%")
    seeded["result"].tags = ["Topic_100%"]
    # An older generated ref on the same version must not contribute its tags.
    history = models.NormalizedAssetRef(
        version_id=seeded["version"].id, normalized_type=seeded["ref"].normalized_type,
        object_uri="normalized/history.json", schema_version="1.0", checksum="history",
        status=seeded["ref"].status, source_type="file_upload", content_type="document",
        title="历史引用", language="zh-CN", governance={}, quality={}, lineage={},
        created_at=seeded["ref"].created_at - timedelta(days=1),
    )
    session.add(history)
    session.flush()
    add_tag(session, seeded, "region", "历史区域", ref_id=history.id)
    add_tag(session, seeded, "topic", "历史主题", ref_id=history.id)
    other = _seed_review_required_asset(session, suffix="other-literal")
    add_tag(session, other, "industry", "RetailX100abc")
    other["result"].tags = ["TopicX100abc"]
    session.commit()
    session.expire_all()
    client = TestClient(app)
    url = "/internal/v1/industry-reports"
    for filters in [{"industry": "retail"}, {"industry": "_100%"}, {"content_tag": "_100%"}]:
        body = client.get(url, params=filters).json()
        assert body["meta"]["total"] == (2 if filters == {"industry": "retail"} else 1)
    for filters in [{"region": "历史"}, {"content_tag": "历史"}, {"region": "Retail"}]:
        assert client.get(url, params=filters).json()["meta"]["total"] == 0


def test_topic_and_title_filters_compose_with_tag_filters(app, session):
    for suffix, title in [("ecommerce", "电商产业报告"), ("aviation", "低空产业报告")]:
        seeded = _seed_review_required_asset(session, suffix=suffix)
        seeded["asset"].title = title
        add_tag(session, seeded, "region", "重庆市")
    profile = _seed_review_required_asset(session, suffix="profile-title")
    profile["result"].classification = "major_profile"
    profile["asset"].title = "电子商务专业简介"
    add_tag(session, profile, "region", "成都市")
    session.commit()
    client = TestClient(app)
    url = "/internal/v1/industry-reports"
    assert client.get(url, params={"region": "重庆", "topic": "finance_commerce"}).json()["meta"]["total"] == 1
    assert client.get(url, params={"region": "成都", "topic": "low_altitude"}).json()["meta"]["total"] == 0
    url = "/internal/v1/major-profile-documents"
    assert client.get(url, params={"region": "成都", "q": "商务"}).json()["meta"]["total"] == 1
    assert client.get(url, params={"region": "重庆", "q": "商务"}).json()["meta"]["total"] == 0
