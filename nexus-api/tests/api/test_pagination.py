"""Pagination contract on `/internal/v1` list endpoints.

Backend used to return the entire table for every list endpoint — a DoS
vector for tenants that accumulate 10k+ assets, audit logs, or jobs. The
fix adds `?page=N&pageSize=M` (camelCase to match the console URL
convention) with a hard ceiling of 200 rows per page (raised from 100 to
align with `docs/pipeline_b_b4_b6_contract_freeze.md §八.4`) and
SELECT COUNT(*) driving `meta.total` so client-side pagination UI shows
the right number of pages.

These tests pin:
  - the bounds (1 ≤ page ≤ 10_000, 1 ≤ pageSize ≤ 200)
  - the slice contract (offset + limit applied at SQL layer)
  - `meta.total` reflects the underlying row count, not the slice
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.enums import (
    AuditEventType,
    DataSourceStatus,
    DataSourceType,
)


def _seed_audit_logs(session: Session, count: int) -> None:
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    for i in range(count):
        session.add(
            models.AuditLog(
                id=f"audit-{i:04d}",
                event_type=AuditEventType.USER_LOGIN_SUCCEEDED,
                target_type="user_account",
                target_id=f"u{i}",
                trace_id=f"t{i}",
                summary={"i": i},
                actor_type="user",
                actor_id="u",
                # Deterministic ordering so the slice assertions are stable.
                created_at=base + timedelta(seconds=i),
            )
        )
    session.commit()


def _seed_data_sources(session: Session, count: int) -> None:
    for i in range(count):
        session.add(
            models.DataSource(
                id=f"ds-{i:04d}",
                code=f"ds-{i:04d}",
                name=f"DS {i}",
                source_type=DataSourceType.FILE_UPLOAD,
                status=DataSourceStatus.ENABLED,
            )
        )
    session.commit()


# ── Bounds enforcement ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "qs",
    [
        "page=0",            # below min
        "page=-1",
        "pageSize=0",
        "pageSize=201",      # above 200 cap
        "pageSize=999999",
        "page=10001",        # above page ceiling
    ],
)
def test_invalid_pagination_returns_422(app, qs):
    with TestClient(app) as client:
        resp = client.get(f"/internal/v1/audit-logs?{qs}")
    assert resp.status_code == 422, resp.text


def test_defaults_when_no_query_params(app, session):
    _seed_audit_logs(session, 30)
    with TestClient(app) as client:
        resp = client.get("/internal/v1/audit-logs")
    assert resp.status_code == 200
    body = resp.json()
    # Default page_size is 20.
    assert len(body["data"]) == 20
    assert body["meta"]["page"] == 1
    assert body["meta"]["page_size"] == 20
    assert body["meta"]["total"] == 30


# ── Slice contract ────────────────────────────────────────────────────────


def test_pagination_slices_at_sql_layer(app, session):
    _seed_audit_logs(session, 50)
    with TestClient(app) as client:
        page1 = client.get("/internal/v1/audit-logs?page=1&pageSize=10")
        page2 = client.get("/internal/v1/audit-logs?page=2&pageSize=10")
        page5 = client.get("/internal/v1/audit-logs?page=5&pageSize=10")

    for resp in (page1, page2, page5):
        assert resp.status_code == 200

    ids_page1 = [row["id"] for row in page1.json()["data"]]
    ids_page2 = [row["id"] for row in page2.json()["data"]]
    ids_page5 = [row["id"] for row in page5.json()["data"]]

    assert len(ids_page1) == 10
    assert len(ids_page2) == 10
    assert len(ids_page5) == 10
    # Disjoint pages.
    assert not set(ids_page1) & set(ids_page2)
    assert not set(ids_page1) & set(ids_page5)
    assert not set(ids_page2) & set(ids_page5)
    # All three reference the same backing set.
    for body in (page1.json(), page2.json(), page5.json()):
        assert body["meta"]["total"] == 50


def test_pagination_total_reflects_underlying_count_not_slice(app, session):
    _seed_data_sources(session, 35)
    with TestClient(app) as client:
        resp = client.get("/internal/v1/data-sources?page=2&pageSize=10")
    body = resp.json()
    assert resp.status_code == 200
    assert body["meta"]["total"] == 35
    assert body["meta"]["page"] == 2
    assert body["meta"]["page_size"] == 10
    assert len(body["data"]) == 10


def test_pagination_past_end_returns_empty_slice_with_correct_total(app, session):
    _seed_audit_logs(session, 12)
    with TestClient(app) as client:
        resp = client.get("/internal/v1/audit-logs?page=5&pageSize=10")
    body = resp.json()
    assert resp.status_code == 200
    assert body["meta"]["total"] == 12
    assert body["data"] == []


# ── Coverage across endpoints — smoke ─────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "/internal/v1/org-units",
        "/internal/v1/users",
        "/internal/v1/api-callers",
        "/internal/v1/data-sources",
        "/internal/v1/ingest/batches",
        "/internal/v1/raw-objects",
        "/internal/v1/jobs",
        "/internal/v1/parse-artifacts",
        "/internal/v1/normalized-refs",
        "/internal/v1/audit-logs",
        "/internal/v1/assets",
    ],
)
def test_list_endpoint_accepts_pagination(app, path):
    with TestClient(app) as client:
        resp = client.get(f"{path}?page=1&pageSize=5")
    assert resp.status_code == 200, f"{path} returned {resp.status_code}: {resp.text[:200]}"
    body = resp.json()
    assert "data" in body
    assert body["meta"]["page"] == 1
    assert body["meta"]["page_size"] == 5
