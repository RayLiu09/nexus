"""Professional document searches match the identity displayed in each row."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from nexus_app import models
from tests.test_asset_catalog_api import _seed_review_required_asset


ROUTES = [
    ("major-profile-documents", "major_profile", "major_profile_manual_metadata"),
    ("talent-demand-reports", "talent_demand_report", "talent_demand_report_manual_identity"),
]


@pytest.mark.parametrize("route,kind,manual_key", ROUTES)
def test_identity_filters_intersect_before_count_and_pagination(app, session, route, kind, manual_key):
    expected = []
    for index, school in enumerate(["重庆职业学院", "重庆职业学院", "成都职业学院"]):
        seeded = _seed_review_required_asset(session, suffix=f"identity-{index}")
        seeded["result"].classification = kind
        seeded["result"].tags = ["产教融合"]
        seeded["ref"].document_metadata = {kind: {
            "major_name": "电子商务", "major_code": "530701", "institution_name": school,
        }}
        if index < 2:
            expected.append(seeded["asset"].id)
    session.commit()
    client = TestClient(app)
    url = f"/internal/v1/{route}"
    params = {"major_name": " 商务 ", "major_code": "5307", "institution_name": "重庆", "pageSize": 1}
    first = client.get(url, params=params)
    assert first.status_code == 200, first.text
    second = client.get(url, params={**params, "page": 2}).json()
    assert first.json()["meta"]["total"] == second["meta"]["total"] == 2
    assert {first.json()["data"][0]["id"], second["data"][0]["id"]} == set(expected)
    assert client.get(url, params={**params, "major_code": "999"}).json()["meta"]["total"] == 0
    assert client.get(url, params={"major_name": " ", "major_code": "", "institution_name": " "}).json()["meta"]["total"] == 3
    for field in ("major_name", "major_code", "institution_name"):
        assert client.get(url, params={field: "x" * 129}).status_code == 422
    if kind == "talent_demand_report":
        assert client.get(url, params={**params, "content_tag": "融合"}).json()["meta"]["total"] == 2
        assert client.get(url, params={**params, "content_tag": "航空"}).json()["meta"]["total"] == 0


@pytest.mark.parametrize("route,kind,manual_key", ROUTES)
def test_identity_search_follows_manual_overrides_and_null_precedence(app, session, route, kind, manual_key):
    seeded = _seed_review_required_asset(session, suffix="manual-identity")
    seeded["result"].classification = kind
    seeded["ref"].document_metadata = {kind: {
        "major_name": "源专业", "major_code": "530701", "institution_name": "源院校",
    }}
    seeded["ref"].metadata_summary = {manual_key: {
        "major_name": "Commerce_100%", "institution_name": "重庆职业学院",
    }}
    # A wildcard-like lookalike must not satisfy the literal identity query.
    lookalike = _seed_review_required_asset(session, suffix="lookalike-identity")
    lookalike["result"].classification = kind
    lookalike["ref"].document_metadata = {kind: {"major_name": "CommerceX100abc"}}
    session.commit()
    client = TestClient(app)
    url = f"/internal/v1/{route}"
    params = {"major_name": "commerce_100%", "major_code": "530701", "institution_name": "重庆"}
    body = client.get(url, params=params).json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["major_name"] == "Commerce_100%"
    assert client.get(url, params={"major_name": "源专业"}).json()["meta"]["total"] == 0
    assert client.get(url, params={"institution_name": "源院校"}).json()["meta"]["total"] == 0
    assert client.get(url, params={"major_name": "_100%"}).json()["meta"]["total"] == 1

    # Profiles allow intentional manual clearing; report identity falls back
    # to the source when its manual value is null or empty.
    seeded["ref"].metadata_summary = {manual_key: {"major_name": None, "major_code": ""}}
    session.commit()
    expected = 0 if kind == "major_profile" else 1
    assert client.get(url, params={"major_name": "源专业"}).json()["meta"]["total"] == expected
    assert client.get(url, params={"major_code": "530701"}).json()["meta"]["total"] == expected


@pytest.mark.parametrize("route,kind,manual_key", ROUTES)
def test_identity_filters_ignore_an_older_ref_on_the_same_version(app, session, route, kind, manual_key):
    seeded = _seed_review_required_asset(session, suffix="old-identity")
    seeded["result"].classification = kind
    seeded["ref"].document_metadata = {kind: {"major_name": "当前专业"}}
    session.add(models.NormalizedAssetRef(
        version_id=seeded["version"].id, normalized_type=seeded["ref"].normalized_type,
        object_uri="normalized/old-identity.json", schema_version="1.0", checksum="old-identity",
        status=seeded["ref"].status, source_type="file_upload", content_type="document",
        title="历史引用", language="zh-CN", governance={}, quality={}, lineage={},
        document_metadata={kind: {"major_name": "历史专业"}},
        created_at=seeded["ref"].created_at - timedelta(days=1),
    ))
    session.commit()
    session.expire_all()
    client = TestClient(app)
    url = f"/internal/v1/{route}"
    assert client.get(url, params={"major_name": "当前"}).json()["meta"]["total"] == 1
    assert client.get(url, params={"major_name": "历史"}).json()["meta"]["total"] == 0
