from fastapi.testclient import TestClient
from pathlib import Path
from sqlalchemy import select

from nexus_app import models
from nexus_app.enums import AuditEventType
from nexus_app.enums import UserRole
from nexus_api.dependencies import require_user
from nexus_app.data_sync import plans
from nexus_app.data_sync.catalog import load_catalog


def _create(client, *, key="create-1", keyword="jobs"):
    return client.post(
        "/internal/v1/data-sync/plans",
        headers={"Idempotency-Key": key},
        json={
            "name": "Monthly jobs",
            "provider_code": "mock",
            "frequency": "1_month",
            "query_config": {"keyword": keyword},
        },
    )


def test_plan_lifecycle_and_audit(app, session):
    with TestClient(app) as client:
        created = _create(client)
        assert created.status_code == 201
        plan = created.json()["data"]
        plan_id = plan["id"]
        assert plan["status"] == "active"
        assert plan["query_config"] == {"keyword": "jobs", "page_size": 20}

        assert _create(client).json()["data"]["id"] == plan_id
        assert _create(client, keyword="other").status_code == 409
        assert client.post(
            f"/internal/v1/data-sync/plans/{plan_id}/pause",
            headers={"Idempotency-Key": "pause-1"},
        ).json()["data"]["status"] == "paused"
        paused_again = client.post(
            f"/internal/v1/data-sync/plans/{plan_id}/pause",
            headers={"Idempotency-Key": "pause-1"},
        )
        assert paused_again.status_code == 200
        assert paused_again.json()["data"]["next_run_at"] is None
        assert client.post(
            f"/internal/v1/data-sync/plans/{plan_id}/resume",
            headers={"Idempotency-Key": "resume-1"},
        ).json()["data"]["status"] == "active"
        assert client.delete(
            f"/internal/v1/data-sync/plans/{plan_id}",
            headers={"Idempotency-Key": "delete-1"},
        ).json()["data"]["status"] == "deleted"
        assert client.get("/internal/v1/data-sync/plans").json()["data"] == []
        assert client.get(f"/internal/v1/data-sync/plans/{plan_id}").status_code == 200
        assert client.post(
            f"/internal/v1/data-sync/plans/{plan_id}/resume",
            headers={"Idempotency-Key": "resume-2"},
        ).status_code == 409

    rows = list(session.scalars(select(models.AuditLog).where(
        models.AuditLog.target_type == "data_sync_config",
        models.AuditLog.target_id == plan_id,
    )))
    assert [row.event_type for row in rows] == [
        AuditEventType.DATA_SYNC_PLAN_CREATED,
        AuditEventType.DATA_SYNC_PLAN_PAUSED,
        AuditEventType.DATA_SYNC_PLAN_RESUMED,
        AuditEventType.DATA_SYNC_PLAN_DELETED,
    ]
    assert all(row.trace_id and row.actor_id == "user-test-admin" for row in rows)


def test_plan_create_rejects_invalid_query_and_requires_key(app):
    with TestClient(app) as client:
        assert _create(client, keyword="").status_code == 422
        assert client.post(
            "/internal/v1/data-sync/plans",
            json={"name": "x", "provider_code": "mock", "frequency": "1_month", "query_config": {}},
        ).status_code == 428


def test_plan_update_writes_update_audit(app, session):
    with TestClient(app) as client:
        created = _create(client)
        assert created.status_code == 201
        plan = created.json()["data"]
        updated = client.put(
            f"/internal/v1/data-sync/plans/{plan['id']}",
            headers={"Idempotency-Key": "update-1"},
            json={
                "name": "Quarterly jobs",
                "frequency": "3_months",
                "query_config": {"keyword": "updated"},
            },
        )
        assert updated.status_code == 200
        assert updated.json()["data"]["name"] == "Quarterly jobs"
        assert updated.json()["data"]["frequency"] == "3_months"
        assert updated.json()["data"]["query_config"] == {
            "keyword": "updated",
            "page_size": 20,
        }

    audit = session.scalar(
        select(models.AuditLog).where(
            models.AuditLog.target_type == "data_sync_config",
            models.AuditLog.target_id == plan["id"],
            models.AuditLog.event_type == AuditEventType.DATA_SYNC_PLAN_UPDATED,
        )
    )
    assert audit is not None


def test_non_admin_cannot_read_catalog_or_create_plan(app, stub_user):
    stub_user.role = UserRole.BUSINESS_EXPERT
    app.dependency_overrides[require_user] = lambda: stub_user
    with TestClient(app) as client:
        assert client.get("/internal/v1/data-sync/providers").status_code == 403
        assert _create(client).status_code == 403


def test_job_plan_custom_input_roundtrip_limits_and_audit(app, session, monkeypatch):
    provider = next(item for item in load_catalog(
        Path(__file__).resolve().parents[2] / "nexus-app/config/data_sync_providers.json"
    ) if item.provider_code == "crawler_engine").model_copy(update={"status": "enabled"})
    monkeypatch.setattr(plans, "load_catalog", lambda: [provider])
    payload = {"name": "自定义岗位计划", "provider_code": "crawler_engine", "frequency": "1_month",
               "query_config": {"keywords": [f"自定义岗位{i}" for i in range(30)], "regions": ["杭州市"]}}
    with TestClient(app) as client:
        created = client.post("/internal/v1/data-sync/plans", headers={"Idempotency-Key": "custom-job-plan"}, json=payload)
        assert created.status_code == 201
        plan = created.json()["data"]
        assert plan["query_config"] == {**payload["query_config"], "pageLimit": 30}
        assert client.post("/internal/v1/data-sync/plans", headers={"Idempotency-Key": "custom-job-plan"}, json={
            **payload, "query_config": {**payload["query_config"], "professional_category": "  "},
        }).json()["data"]["id"] == plan["id"]
        changed_query = {"keywords": ["低空运营专员"], "regions": ["杭州市"], "professional_category": "  低空经济类  "}
        updated = client.put(f"/internal/v1/data-sync/plans/{plan['id']}", headers={"Idempotency-Key": "custom-edit"}, json={
            "name": payload["name"], "frequency": "1_month", "query_config": changed_query,
        })
        assert updated.status_code == 200
        query = {**changed_query, "professional_category": "低空经济类", "pageLimit": 30}
        assert updated.json()["data"]["query_config"] == query
        assert client.get(f"/internal/v1/data-sync/plans/{plan['id']}").json()["data"]["query_config"] == query
        cleared = client.put(f"/internal/v1/data-sync/plans/{plan['id']}", headers={"Idempotency-Key": "custom-clear"}, json={
            "name": payload["name"], "frequency": "1_month", "query_config": {**query, "professional_category": ""},
        })
        assert cleared.status_code == 200
        assert "professional_category" not in cleared.json()["data"]["query_config"]
        invalid_query = {**query, "keywords": [f"岗位{i}" for i in range(31)]}
        assert client.post("/internal/v1/data-sync/plans", headers={"Idempotency-Key": "31-jobs"}, json={
            **payload, "query_config": invalid_query,
        }).status_code == 422
        assert client.put(f"/internal/v1/data-sync/plans/{plan['id']}", headers={"Idempotency-Key": "31-edit"}, json={
            "name": payload["name"], "frequency": "1_month", "query_config": invalid_query,
        }).status_code == 422
    audits = list(session.scalars(select(models.AuditLog).where(models.AuditLog.target_id == plan["id"])))
    assert [audit.event_type for audit in audits] == [AuditEventType.DATA_SYNC_PLAN_CREATED,
        AuditEventType.DATA_SYNC_PLAN_UPDATED, AuditEventType.DATA_SYNC_PLAN_UPDATED]
    assert all(audit.actor_id == "user-test-admin" and audit.trace_id for audit in audits)
