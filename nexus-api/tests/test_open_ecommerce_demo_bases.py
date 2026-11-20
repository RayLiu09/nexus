"""Public demonstration-base contracts, SQL scope, source safety and caller audit."""
from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from nexus_app import auth_service, models
from nexus_app.enums import AuditEventType
from test_ecommerce_demo_bases_api import _seed

ROOT = "/open/v1/ecommerce-demo-bases"


def test_list_detail_and_groups_use_stored_records_without_reading_raw_payload(app, session):
    _seed(session)
    row = session.get(models.EcommercePark, "national-1")
    row.source_payload = {"private_unpublished_field": "x" * 100000}
    session.commit()
    session.expire_all()
    queries = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(session.bind, "before_cursor_execute", capture)
    try:
        client = TestClient(app)
        rows = client.get(ROOT, params={"pageSize": 1}, headers={"X-Trace-ID": "base-list-trace"})
        assert rows.status_code == 200
        assert rows.json()["meta"]["total"] == 3 and len(rows.json()["data"]) == 1
        item = rows.json()["data"][0]
        assert item["id"] == "national-1" and item["batch_name"] == "首批"
        assert item["source_url"] == "https://dzswgf.mofcom.gov.cn/news/1/2020/9/1.html"
        detail = client.get(ROOT + "/national-1").json()["data"]
        assert detail["source_file"] == "国家电子商务示范基地.json"
        assert detail["source_locator"] == "/0/datalist/0"
        assert {key: detail[key] for key in item} == item
        aggregate = client.get(ROOT + "/aggregate", params={"group_by": "level", "pageSize": 1}).json()
        assert aggregate["meta"]["total"] == 2 and len(aggregate["data"]) == 1
        assert aggregate["data"][0] == {"dimensions": {"level": "national"}, "record_count": 2}
        info = aggregate["aggregations"]
        assert info["matched_total"] == info["coverage"]["imported_total"] == 3
        assert info["missing_counts"] == {"level": 0}
        assert {x["level"]: x["record_count"] for x in info["coverage"]["source_files"]} == {"national": 2, "provincial": 1}
        assert info["coverage"]["unit"] == "registry_records"
        assert "operator" in info["coverage"]["unavailable_fields"]
        assert "source_payload" not in rows.text and "private_unpublished_field" not in json.dumps(detail)
        assert not ({"normalized_ref_id", "asset_id", "operator", "detailed_address"} & item.keys())
    finally:
        event.remove(session.bind, "before_cursor_execute", capture)
    assert not any("ecommerce_parks.source_payload" in q for q in queries)
    audits = session.scalars(select(models.AuditLog).where(models.AuditLog.target_type == "public_data_read")).all()
    assert len(audits) == 3
    listed = next(x for x in audits if x.trace_id == "base-list-trace")
    assert listed.actor_type == "api_caller" and listed.actor_id
    assert listed.event_type == AuditEventType.SEARCH_QUERY_EXECUTED
    assert listed.summary["record_ids"] == ["national-1"]
    assert "mofcom.gov.cn" not in json.dumps([x.summary for x in audits])


def test_list_aggregate_share_all_filters_and_do_not_return_broader_empty_scope(app, session):
    _seed(session)
    client = TestClient(app)
    params = {"level": "national", "q": "商务", "province_code": "320000", "batch": "first", "recognized_year": 2020}
    rows = client.get(ROOT, params=params).json()
    aggregate = client.get(ROOT + "/aggregate", params={**params, "group_by": "recognized_year"}).json()
    assert rows["meta"]["total"] == aggregate["aggregations"]["matched_total"] == 1
    assert aggregate["data"] == [{"dimensions": {"recognized_year": 2020}, "record_count": 1}]
    params["recognized_year"] = 2021
    assert client.get(ROOT, params=params).json()["meta"]["total"] == 0
    empty = client.get(ROOT + "/aggregate", params=params).json()
    assert empty["meta"]["total"] == empty["aggregations"]["matched_total"] == 0
    assert empty["data"] == []
    # Coverage describes the full snapshot, not matching rows.
    assert empty["aggregations"]["coverage"]["imported_total"] == 3
    audits = session.scalars(select(models.AuditLog)).all()
    assert all("q" not in row.summary and "商务" not in json.dumps(row.summary) for row in audits)


@pytest.mark.parametrize("query", ["%", "_", "\\", "%' OR 1=1 --"])
def test_names_match_literal_substrings_not_sql_patterns(app, session, query):
    _seed(session)
    client = TestClient(app)
    assert client.get(ROOT, params={"q": query}).json()["meta"]["total"] == 0
    result = client.get(ROOT + "/aggregate", params={"q": query}).json()
    assert result["aggregations"]["matched_total"] == 0


def test_groups_preserve_missing_values_and_never_merge_same_name_records(app, session):
    _seed(session)
    row = session.get(models.EcommercePark, "national-2")
    row.province_code = None
    row.province_name = None
    row.recognized_year = None
    session.get(models.EcommercePark, "provincial-1").title = "江苏数字商务基地"
    session.commit()
    client = TestClient(app)
    by_batch = client.get(ROOT + "/aggregate", params={"group_by": "batch_code"}).json()
    assert by_batch["aggregations"]["missing_counts"] == {"batch_code": 1}
    assert {x["dimensions"]["batch_code"] for x in by_batch["data"]} == {"first", "second", None}
    both = client.get(ROOT, params={"q": "江苏数字商务基地"}).json()
    assert both["meta"]["total"] == 2
    grouped = client.get(ROOT + "/aggregate", params=[("group_by", "province_code"), ("group_by", "recognized_year")]).json()
    assert grouped["aggregations"]["missing_counts"] == {"province_code": 1, "recognized_year": 1}
    assert sum(x["record_count"] for x in grouped["data"]) == 3
    assert client.get(ROOT, params={"recognized_year": 2021}).json()["meta"]["total"] == 0
    # Whitespace province codes count as missing too; source field is not rewritten.
    row.province_code = ""
    session.commit()
    grouped = client.get(ROOT + "/aggregate", params={"group_by": "province_code"}).json()
    assert grouped["aggregations"]["missing_counts"] == {"province_code": 1}
    national = next(x for x in grouped["aggregations"]["coverage"]["source_files"] if x["level"] == "national")
    assert national["province_count"] == 1


def test_pagination_is_stable_and_provincial_dates_keep_source_meaning(app, session):
    _seed(session)
    client = TestClient(app)
    ids = [client.get(ROOT, params={"pageSize": 1, "page": page}).json()["data"][0]["id"] for page in (1, 2, 3)]
    assert ids == ["national-1", "national-2", "provincial-1"]
    assert client.get(ROOT, params={"pageSize": 1, "page": 4}).json()["data"] == []
    item = client.get(ROOT, params={"level": "provincial", "province_code": "320000", "recognized_year": 2019}).json()["data"][0]
    assert item["recognized_period"] == "2019年7月" and item["source_publish_at"].startswith("2019-08-01")
    assert item["batch_code"] is None


@pytest.mark.parametrize("path", ["", "/aggregate", "/national-1"])
def test_source_links_are_safe_and_public_routes_are_read_only(app, session, path):
    _seed(session)
    client = TestClient(app)
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert client.request(method, ROOT + path).status_code == 405
    assert client.get(ROOT + "/missing").status_code == 404
    assert client.get(ROOT + "/national-2").json()["data"]["source_url"] is None
    row = session.get(models.EcommercePark, "national-1")
    for source_path in ("//evil.example/a", "https://evil.example/a", "/news/../1.html", "/news/1/2020/9/1.html?secret=x"):
        row.source_path = source_path
        session.commit()
        assert client.get(ROOT + "/national-1").json()["data"]["source_url"] is None


@pytest.mark.parametrize("params", [
    {"level": "invalid"}, {"level": "provincial", "batch": "first"}, {"batch": "invalid"},
    {"province_code": "重庆"}, {"recognized_year": 0}, {"q": " "}, {"page": 0}, {"pageSize": 201},
])
def test_invalid_filters_and_pagination_fail_422(app, params):
    client = TestClient(app)
    for path in (ROOT, ROOT + "/aggregate"):
        assert client.get(path, params=params).status_code == 422


@pytest.mark.parametrize("groups", [["invalid"], ["level", "level"], ["level"] * 5])
def test_invalid_grouping_fails_422(app, groups):
    assert TestClient(app).get(ROOT + "/aggregate", params={"group_by": groups}).status_code == 422


@pytest.mark.parametrize("path", ["", "/aggregate", "/national-1"])
def test_real_authentication_and_revocation_expiration(app_no_auth_override, session, path):
    _seed(session)
    client = TestClient(app_no_auth_override)
    assert client.get(ROOT + path).status_code == 401
    assert client.get(ROOT + path, headers={"X-API-Key": "wrong"}).status_code == 401
    key = auth_service.generate_api_caller_key()
    caller = models.ApiCaller(name="Public base caller", caller_key_hash=auth_service.hash_api_caller_key(key),
                              permission_scope=["open:*"], org_scope=[])
    session.add(caller)
    session.commit()
    assert client.get(ROOT + path, headers={"X-API-Key": key}).status_code == 200
    caller.revoked_at = datetime.now(timezone.utc)
    session.commit()
    assert client.get(ROOT + path, headers={"X-API-Key": key}).status_code == 403
    caller.revoked_at = None
    caller.expired_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session.commit()
    assert client.get(ROOT + path, headers={"X-API-Key": key}).status_code == 403
    assert session.scalar(select(models.AuditLog).where(models.AuditLog.actor_id == caller.id)) is not None


@pytest.mark.parametrize("path", ["", "/aggregate", "/national-1"])
def test_revocation_during_read_is_rechecked_before_audit_and_return(app_no_auth_override, session, monkeypatch, path):
    from nexus_api.api import open_ecommerce_demo_bases as api
    _seed(session)
    key = auth_service.generate_api_caller_key()
    caller = models.ApiCaller(name="Mid-flight", caller_key_hash=auth_service.hash_api_caller_key(key), org_scope=[], permission_scope=[])
    session.add(caller)
    session.commit()
    original = api.audit_read

    def revoke(*args, **kwargs):
        caller.revoked_at = datetime.now(timezone.utc)
        session.commit()
        return original(*args, **kwargs)

    monkeypatch.setattr(api, "audit_read", revoke)
    result = TestClient(app_no_auth_override).get(ROOT + path, headers={"X-API-Key": key})
    assert result.status_code == 403
    assert not session.scalars(select(models.AuditLog)).all()


def test_discovery_exposes_base_counts_parameters_and_only_real_capabilities(app, session):
    _seed(session)
    data = TestClient(app).get("/open/v1/data-resources").json()["data"]
    item = next(x for x in data if x["code"] == "ecommerce_demo_base")
    assert len(data) == 18 and item["count"] == 3
    assert item["endpoint"] == ROOT
    assert item["knowledge_types"] == []
    assert item["retrieval_capabilities"] == ["catalog", "structured_query"]
    assert item["capabilities"] == ["list", "detail", "aggregate"]
    assert {"level", "q", "province_code", "recognized_year", "batch"} <= set(item["filter_parameters"])
