from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_app import models
from nexus_app.enums import AuditEventType
from nexus_app.enums import UserRole
from nexus_api.dependencies import require_user


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


def test_non_admin_cannot_read_catalog_or_create_plan(app, stub_user):
    stub_user.role = UserRole.BUSINESS_EXPERT
    app.dependency_overrides[require_user] = lambda: stub_user
    with TestClient(app) as client:
        assert client.get("/internal/v1/data-sync/providers").status_code == 403
        assert _create(client).status_code == 403
