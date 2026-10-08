from fastapi.testclient import TestClient

from nexus_api.dependencies import require_user
from nexus_app import models
from nexus_app.enums import AuditEventType, UserRole


def _create(client):
    plan = client.post(
        "/internal/v1/data-sync/plans",
        headers={"Idempotency-Key": "log-plan"},
        json={
            "name": "Audit plan", "provider_code": "mock", "frequency": "1_month",
            "query_config": {"keyword": "jobs"},
        },
    ).json()["data"]
    run = client.post(
        f"/internal/v1/data-sync/plans/{plan['id']}/runs",
        headers={"Idempotency-Key": "log-run"},
    ).json()["data"]
    return plan, run


def test_run_log_filters_redacts_and_preserves_deleted_history(app, session):
    with TestClient(app) as client:
        plan, run = _create(client)
        run_row = session.get(models.DataSyncRun, run["id"])
        run_row.status = "succeeded"
        run_row.query_snapshot = {
            "keyword": "jobs", "tenant_key": "private-value",
            "notes": "x" * 1000,
        }
        run_row.failure_summary = "failure: " + "x" * 1000
        session.add(models.AuditLog(
            event_type=AuditEventType.DATA_SYNC_RUN_CONTROLLED,
            target_type="data_sync_run", target_id=run["id"],
            trace_id="trace-log", actor_type="user", actor_id="admin",
            summary={
                "action": "pause", "outcome": "failed", "error_code": "control_unavailable",
                "idempotency_key_hash": "hidden-hash", "tenant_key": "hidden-key",
                "raw_response": "hidden-response",
            },
        ))
        session.commit()
        assert client.delete(
            f"/internal/v1/data-sync/plans/{plan['id']}",
            headers={"Idempotency-Key": "delete-log-plan"},
        ).status_code == 200

        listing = client.get(f"/internal/v1/data-sync/runs?run_id={run['id']}")
        assert listing.status_code == 200
        assert listing.json()["meta"]["total"] == 1
        assert client.get("/internal/v1/data-sync/runs?run_id=missing").json()["meta"]["total"] == 0
        logs = client.get(f"/internal/v1/data-sync/runs/{run['id']}/logs?pageSize=1")
        assert logs.status_code == 200
        data = logs.json()["data"]
        assert data["adapter_version"] == run["adapter_version"]
        assert data["query_hash"] == run["query_hash"]
        assert data["audit_total"] == 2
        assert len(data["audit_events"]) == 1
        assert "***redacted***" in data["query_summary"]
        assert len(data["query_summary"]) <= 600
        assert len(data["failure_summary"]) <= 500
        assert "private-value" not in logs.text
        assert "hidden-hash" not in logs.text
        assert "hidden-key" not in logs.text
        assert "hidden-response" not in logs.text
        assert client.get(f"/internal/v1/data-sync/runs/{run['id']}/logs?page=2&pageSize=1").status_code == 200
        assert client.get("/internal/v1/data-sync/runs/missing/logs").status_code == 404


def test_run_logs_require_admin(app, stub_user):
    stub_user.role = UserRole.BUSINESS_EXPERT
    app.dependency_overrides[require_user] = lambda: stub_user
    with TestClient(app) as client:
        assert client.get("/internal/v1/data-sync/runs/any/logs").status_code == 403
