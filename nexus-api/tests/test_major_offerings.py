from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import select
from nexus_app import models


def seed(session):
    plan = models.DataSyncConfig(
        id="moe-plan",
        name="教育部",
        provider_code="moe_major_offering",
        frequency="1_year",
        query_config={},
        created_by="admin",
        idempotency_key="plan",
        request_hash="moe",
    )
    run = models.DataSyncRun(
        id="moe-run",
        data_sync_config_id=plan.id,
        provider_code="moe_major_offering",
        adapter_version="1",
        query_snapshot={},
        query_hash="moe",
        trace_id="test",
        status="succeeded",
    )
    session.add_all([plan, run])
    session.flush()
    for i, year, province, school in [
        (1, 2026, "北京市", "学校甲"),
        (2, 2026, "北京市", "学校乙"),
        (3, 2025, "江苏省", "学校甲"),
    ]:
        session.add(
            models.MajorOfferingRecord(
                id=str(i),
                sync_run_id=run.id,
                provider_code="moe_major_offering",
                year=year,
                province_code="BJ" if i < 3 else "JS",
                province_name=province,
                major_code="530701",
                major_name="电子商务",
                school_code=None,
                school_name=school,
                school_name_key=school,
                study_duration="3",
                remark=None,
                source_url="https://zwfw.moe.gov.cn/zyyxzy/result.html",
                fetched_at=datetime.now(timezone.utc),
            )
        )
    session.commit()


def test_filters_aggregation_audit_and_read_only(app, session):
    seed(session)
    client = TestClient(app)
    result = client.get(
        "/v1/major-offerings", params={"year": 2026, "province_name": "北京", "school_name": "甲"}
    )
    assert result.status_code == 200, result.text
    assert len(result.json()["data"]) == 1 and result.json()["data"][0]["school_name"] == "学校甲"
    assert "school_name_key" not in result.json()["data"][0]
    result = client.get(
        "/open/v1/major-offerings/aggregate", params={"year": 2026, "group_by": "province_name"}
    )
    assert result.status_code == 200, result.text
    assert result.json()["data"] == [
        {"province_name": "北京市", "record_count": 2, "institution_count": 2}
    ]
    assert (
        client.get("/v1/major-offerings/aggregate", params={"group_by": "__class__"}).status_code
        == 422
    )
    assert client.get("/internal/v1/major-offerings").status_code == 200
    assert client.get("/internal/v1/record-assets/major-distribution-records").status_code == 410
    assert client.get("/open/v1/record-assets/major-distribution-records").status_code == 410
    for method in (client.post, client.patch, client.delete):
        assert method("/v1/major-offerings").status_code == 405
        assert method("/internal/v1/major-offerings").status_code == 405
    assert (
        client.patch(
            "/internal/v1/record-assets/major-distribution-records/old", json={}
        ).status_code
        == 405
    )
    assert len(list(session.scalars(select(models.AuditLog)))) == 3


def test_authentication_is_required(app_no_auth_override):
    client = TestClient(app_no_auth_override)
    for path in ("/v1/major-offerings", "/open/v1/major-offerings", "/internal/v1/major-offerings"):
        assert client.get(path).status_code in (401, 403)


def test_public_provider_options_and_required_plan_parameters(app, monkeypatch):
    from nexus_app.data_sync.catalog import DEFAULT_CATALOG_PATH
    from nexus_app.data_sync.adapters.moe_major_offering import MoeMajorOfferingProvider

    monkeypatch.setenv("DATA_SYNC_PROVIDER_CATALOG_PATH", str(DEFAULT_CATALOG_PATH))
    monkeypatch.setattr(
        MoeMajorOfferingProvider,
        "get_options",
        lambda *_: {"years": [2026, 2025], "provinces": [{"code": "HeB", "name": "河北省"}]},
    )
    client = TestClient(app)
    data = client.get("/internal/v1/data-sync/providers").json()["data"]
    provider = next(p for p in data if p["provider_code"] == "moe_major_offering")
    assert provider["auth_mode"] == "none" and provider["credential_status"] == "not_required"
    assert provider.get("tenant_name") is None and "tenant_key" not in provider
    options = client.get("/internal/v1/data-sync/providers/moe_major_offering/options")
    assert options.status_code == 200 and options.json()["data"]["provinces"][0]["code"] == "HeB"
    body = {
        "name": "备案同步",
        "provider_code": "moe_major_offering",
        "frequency": "1_year",
        "query_config": {
            "year": 2026,
            "province": "HeB",
            "major_code": "530701",
            "major_name": "电子商务",
        },
    }
    response = client.post(
        "/internal/v1/data-sync/plans", json=body, headers={"Idempotency-Key": "ministry-valid"}
    )
    assert response.status_code == 201, response.text
    for key in body["query_config"]:
        invalid = {
            **body,
            "query_config": {k: v for k, v in body["query_config"].items() if k != key},
        }
        assert (
            client.post(
                "/internal/v1/data-sync/plans",
                json=invalid,
                headers={"Idempotency-Key": "missing-" + key},
            ).status_code
            == 422
        )


def test_evidence_resolution_reads_new_domain_without_legacy_asset_reference(app, session):
    seed(session)
    client = TestClient(app)
    result = client.post(
        "/open/v1/evidence-resolutions",
        json={"references": [{"kind": "major_distribution", "id": "1"}], "max_chars": 2000},
    )
    assert result.status_code == 200, result.text
    item = result.json()["data"][0]
    assert item["status"] == "available"
    assert "学校甲" in item["content"]
    assert "zwfw.moe.gov.cn" in item["content"]
    assert item.get("normalized_ref_id") is None
    assert "normalized_ref_id" not in item["content"]
