from datetime import datetime, timezone

from fastapi.testclient import TestClient

from nexus_app import models


def _seed(session):
    session.add_all(
        [
            models.EcommercePark(
                id="national-1",
                level="national",
                source_path="/news/1/2020/9/1.html",
                title="江苏数字商务基地",
                province_code="320000",
                province_name="江苏省",
                batch_code="first",
                recognized_period="2020年9月",
                recognized_year=2020,
                recognized_month=9,
                source_link_enabled=True,
                source_order=1,
                source_locator="/0/datalist/0",
                source_payload={"TITLE": "江苏数字商务基地"},
            ),
            models.EcommercePark(
                id="national-2",
                level="national",
                source_path="/news/2/2021/7/2.html",
                title="山东电商基地",
                province_code="370000",
                province_name="山东省",
                batch_code="second",
                recognized_period="2021年7月",
                recognized_year=2021,
                recognized_month=7,
                source_link_enabled=False,
                source_order=2,
                source_locator="/1/datalist/0",
                source_payload={"TITLE": "山东电商基地"},
            ),
            models.EcommercePark(
                id="provincial-1",
                level="provincial",
                source_path="/news/3/2019/7/3.html",
                title="江苏省电商示范基地",
                province_code="320000",
                province_name="江苏省",
                recognized_period="2019年7月",
                recognized_year=2019,
                recognized_month=7,
                source_publish_at=datetime(2019, 8, 1, tzinfo=timezone.utc),
                source_link_enabled=True,
                source_order=1,
                source_locator="/datalist/0",
                source_payload={"TITLE": "江苏省电商示范基地"},
            ),
        ]
    )
    session.commit()


def test_ecommerce_demo_bases_list_and_aggregate_share_filters(app, session):
    _seed(session)
    client = TestClient(app)

    rows = client.get(
        "/internal/v1/ecommerce-demo-bases",
        params={"level": "national", "batch": "first", "pageSize": 20},
    )
    assert rows.status_code == 200
    assert rows.json()["meta"]["total"] == 1
    assert rows.json()["data"][0]["batch_name"] == "首批"
    assert rows.json()["data"][0]["source_url"].startswith("https://dzswgf.mofcom.gov.cn/")

    aggregate = client.get(
        "/internal/v1/ecommerce-demo-bases/aggregate",
        params={"level": "national", "batch": "first"},
    )
    assert aggregate.status_code == 200
    data = aggregate.json()["data"]
    assert data["matched_total"] == 1
    assert data["batch_counts"] == [{"code": "first", "name": "首批", "count": 1}]
    assert data["province_counts"] == [
        {"province_code": "320000", "province_name": "江苏省", "count": 1}
    ]
    assert data["filter_options"]["batches"][1]["name"] == "第二批"
    assert data["coverage"]["imported_total"] == 2


def test_ecommerce_demo_bases_is_read_only_and_rejects_invalid_provincial_filters(app, session):
    _seed(session)
    client = TestClient(app)
    assert client.post("/internal/v1/ecommerce-demo-bases", params={"level": "national"}).status_code == 405
    assert (
        client.get(
            "/internal/v1/ecommerce-demo-bases",
            params={"level": "provincial", "batch": "first"},
        ).status_code
        == 422
    )
    provincial = client.get(
        "/internal/v1/ecommerce-demo-bases", params={"level": "provincial"}
    )
    assert provincial.status_code == 200
    assert provincial.json()["data"][0]["source_publish_at"].startswith("2019-08-01")


def test_asset_center_counts_include_ecommerce_demo_bases(app, session):
    _seed(session)
    response = TestClient(app).get("/internal/v1/asset-center/counts")
    assert response.status_code == 200
    assert response.json()["data"]["counts"]["market/ecommerce-demo-bases"] == 3


def test_literal_name_search_does_not_treat_wildcards_as_patterns(app, session):
    _seed(session)
    client = TestClient(app)
    for q in ("%", "_", "\\", "%' OR 1=1 --"):
        result = client.get("/internal/v1/ecommerce-demo-bases", params={"level": "national", "q": q})
        aggregate = client.get("/internal/v1/ecommerce-demo-bases/aggregate", params={"level": "national", "q": q})
        assert result.status_code == aggregate.status_code == 200
        assert result.json()["meta"]["total"] == aggregate.json()["data"]["matched_total"] == 0


def test_pagination_and_combined_filters_are_database_scoped(app, session):
    _seed(session)
    client = TestClient(app)
    result = client.get("/internal/v1/ecommerce-demo-bases", params={"level": "national", "page": 2, "pageSize": 1})
    assert result.json()["meta"]["total"] == 2
    assert [row["id"] for row in result.json()["data"]] == ["national-2"]
    assert result.json()["data"][0]["source_url"] is None
    assert "source_payload" not in result.json()["data"][0]
    params = {"level": "national", "q": "商务", "province_code": "320000", "recognized_year": 2020, "batch": "first"}
    result = client.get("/internal/v1/ecommerce-demo-bases", params=params)
    aggregate = client.get("/internal/v1/ecommerce-demo-bases/aggregate", params=params)
    assert result.json()["meta"]["total"] == aggregate.json()["data"]["matched_total"] == 1
    assert len(aggregate.json()["data"]["filter_options"]["provinces"]) == 2
    params["recognized_year"] = 2021
    assert client.get("/internal/v1/ecommerce-demo-bases", params=params).json()["meta"]["total"] == 0


def test_provincial_view_can_filter_by_persisted_province(app, session):
    _seed(session)
    client = TestClient(app)
    params = {"level": "provincial", "province_code": "320000"}
    assert client.get("/internal/v1/ecommerce-demo-bases", params=params).json()["meta"]["total"] == 1
    data = client.get("/internal/v1/ecommerce-demo-bases/aggregate", params=params).json()["data"]
    assert data["province_counts"] == data["batch_counts"] == []
    assert data["filter_options"]["provinces"] == [{"province_code": "320000", "province_name": "江苏省", "count": 1}]
    params["province_code"] = "370000"
    assert client.get("/internal/v1/ecommerce-demo-bases", params=params).json()["meta"]["total"] == 0


def test_unauthenticated_read_and_unsupported_write_methods(app_no_auth_override, app):
    anonymous = TestClient(app_no_auth_override)
    authenticated = TestClient(app)
    for endpoint in ("/internal/v1/ecommerce-demo-bases", "/internal/v1/ecommerce-demo-bases/aggregate"):
        assert anonymous.get(endpoint, params={"level": "national"}).status_code == 401
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            assert authenticated.request(method, endpoint).status_code == 405
        for params in ({}, {"level": "invalid"}, {"level": "national", "province_code": "../"}, {"level": "national", "recognized_year": 0}):
            assert authenticated.get(endpoint, params=params).status_code == 422


def test_complete_source_snapshot_statistics_and_pagination(app, session):
    import json
    from pathlib import Path
    from scripts.import_ecommerce_demo_bases import _national_rows, _provincial_rows

    root = Path(__file__).resolve().parents[2]
    national = _national_rows(json.loads((root / "docs/samples/国家电子商务示范基地.json").read_text()))
    provincial, _ = _provincial_rows(json.loads((root / "docs/samples/省级电子商务示范基地.json").read_text()))
    session.add_all([models.EcommercePark(**row) for row in [*national, *provincial]])
    session.commit()
    client = TestClient(app)
    aggregate = client.get("/internal/v1/ecommerce-demo-bases/aggregate", params={"level": "national"}).json()["data"]
    assert aggregate["matched_total"] == sum(row["count"] for row in aggregate["province_counts"]) == 170
    assert {row["code"]: row["count"] for row in aggregate["batch_counts"]} == {"first": 34, "second": 63, "supplement": 73}
    province = client.get("/internal/v1/ecommerce-demo-bases/aggregate", params={"level": "provincial"}).json()["data"]
    assert province["matched_total"] == 142
    assert {row["province_code"]: row["count"] for row in province["filter_options"]["provinces"]} == {"320000": 79, "370000": 33, "410000": 9, "420000": 18, "450000": 1, "620000": 2}
    rows = client.get("/internal/v1/ecommerce-demo-bases", params={"level": "provincial", "page": 8, "pageSize": 20}).json()
    assert rows["meta"]["total"] == 142 and len(rows["data"]) == 2
