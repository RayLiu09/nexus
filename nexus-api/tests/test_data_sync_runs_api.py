from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
import pytest

from nexus_app import models
from nexus_app.data_sync import runs
from nexus_app.data_sync.catalog import load_catalog
from nexus_app.enums import AuditEventType


def _plan(client):
    response = client.post(
        "/internal/v1/data-sync/plans",
        headers={"Idempotency-Key": "plan-for-runs"},
        json={
            "name": "Monthly jobs", "provider_code": "mock",
            "frequency": "1_month", "query_config": {"keyword": "jobs"},
        },
    )
    assert response.status_code == 201
    return response.json()["data"]["id"]


def _run(client, plan_id, key="run-1"):
    return client.post(
        f"/internal/v1/data-sync/plans/{plan_id}/runs",
        headers={"Idempotency-Key": key},
    )


def test_run_create_idempotency_exclusion_deletion_and_audit(app, session):
    with TestClient(app) as client:
        plan_id = _plan(client)
        first = _run(client, plan_id)
        assert first.status_code == 201
        run = first.json()["data"]
        assert run["status"] == "queued"
        assert run["query_snapshot"] == {"keyword": "jobs", "page_size": 20}
        assert len(run["query_hash"]) == 64
        assert run["adapter_version"] == "1.0.0"
        assert "tenant_key" not in first.text
        assert _run(client, plan_id).json()["data"]["id"] == run["id"]
        assert _run(client, plan_id, "run-2").status_code == 409
        assert client.delete(
            f"/internal/v1/data-sync/plans/{plan_id}",
            headers={"Idempotency-Key": "delete-run-plan"},
        ).status_code == 409

        session.get(models.DataSyncRun, run["id"]).status = "succeeded"
        session.commit()
        second = _run(client, plan_id, "run-2")
        assert second.status_code == 201
        assert second.json()["data"]["id"] != run["id"]
        assert second.json()["data"]["query_hash"] == run["query_hash"]

        listing = client.get(
            f"/internal/v1/data-sync/runs?plan_id={plan_id}&page=1&pageSize=1"
        )
        assert listing.status_code == 200
        assert listing.json()["meta"]["total"] == 2
        assert len(listing.json()["data"]) == 1
        assert client.get(
            "/internal/v1/data-sync/runs?status=succeeded"
        ).json()["meta"]["total"] == 1
        assert client.get(f"/internal/v1/data-sync/runs/{run['id']}").status_code == 200
        assert client.get("/internal/v1/data-sync/runs/missing").status_code == 404

    audits = list(session.scalars(select(models.AuditLog).where(
        models.AuditLog.target_type == "data_sync_run",
    )))
    assert len(audits) == 2
    assert all(row.event_type == AuditEventType.DATA_SYNC_RUN_QUEUED for row in audits)
    assert all(row.trace_id and "query_snapshot" not in row.summary for row in audits)


def test_run_snapshot_stays_fixed_after_plan_and_catalog_change(app, session, monkeypatch):
    with TestClient(app) as client:
        plan_id = _plan(client)
        created = _run(client, plan_id).json()["data"]
        plan = session.get(models.DataSyncConfig, plan_id)
        plan.query_config = {"keyword": "changed", "page_size": 10}
        session.commit()
        provider = load_catalog()[0].model_copy(update={"adapter_version": "2.0.0"})
        monkeypatch.setattr(runs, "load_catalog", lambda: [provider])
        original = client.get(f"/internal/v1/data-sync/runs/{created['id']}").json()["data"]
        assert original["query_snapshot"] == created["query_snapshot"]
        assert original["query_hash"] == created["query_hash"]
        assert original["adapter_version"] == "1.0.0"
        session.get(models.DataSyncRun, created["id"]).status = "succeeded"
        session.commit()
        newer = _run(client, plan_id, "new-parameters").json()["data"]
        assert newer["query_snapshot"] == {"keyword": "changed", "page_size": 10}
        assert newer["adapter_version"] == "2.0.0"
        assert newer["query_hash"] != created["query_hash"]


def test_database_rejects_second_nonterminal_run_and_allows_terminal_history(app, session):
    with TestClient(app) as client:
        plan_id = _plan(client)
        first_id = _run(client, plan_id).json()["data"]["id"]
    second = models.DataSyncRun(
        data_sync_config_id=plan_id, provider_code="mock", adapter_version="1.0.0",
        query_snapshot={}, query_hash="0" * 64, trace_id="trace-second",
    )
    session.add(second)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
    session.get(models.DataSyncRun, first_id).status = "succeeded"
    session.commit()
    session.add(second)
    session.commit()
    assert second.id != first_id


def test_terminal_run_does_not_block_plan_deletion(app, session):
    with TestClient(app) as client:
        plan_id = _plan(client)
        run_id = _run(client, plan_id).json()["data"]["id"]
        session.get(models.DataSyncRun, run_id).status = "cancelled"
        session.commit()
        assert client.delete(
            f"/internal/v1/data-sync/plans/{plan_id}",
            headers={"Idempotency-Key": "delete-terminal-plan"},
        ).status_code == 200
        assert _run(client, plan_id).status_code == 409


def test_paused_and_deleted_plans_do_not_create_runs(app):
    with TestClient(app) as client:
        plan_id = _plan(client)
        assert _run(client, plan_id, "").status_code == 400
        assert client.post(
            f"/internal/v1/data-sync/plans/{plan_id}/pause",
            headers={"Idempotency-Key": "pause-plan"},
        ).status_code == 200
        assert _run(client, plan_id).status_code == 409
        assert _run(client, plan_id, "run-1").status_code == 409
        assert client.delete(
            f"/internal/v1/data-sync/plans/{plan_id}",
            headers={"Idempotency-Key": "delete-plan"},
        ).status_code == 200
        assert _run(client, plan_id).status_code == 409


def test_run_list_validates_status_and_time_range(app):
    with TestClient(app) as client:
        assert client.get("/internal/v1/data-sync/runs?status=unknown").status_code == 422
        assert client.get(
            "/internal/v1/data-sync/runs?created_from=2026-10-02T00:00:00Z"
            "&created_to=2026-10-01T00:00:00Z"
        ).status_code == 422
        assert client.get(
            "/internal/v1/data-sync/runs?created_from=2026-10-02T00:00:00"
        ).status_code == 422
