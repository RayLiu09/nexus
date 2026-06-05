"""DELETE /v1/data-sources/{id}."""
from __future__ import annotations

import itertools

from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_app import models
from nexus_app.enums import (
    AuditEventType,
    DataSourceStatus,
    DataSourceType,
    IngestBatchStatus,
    RawObjectStatus,
)

_counter = itertools.count(1)


def _seed_source(session, *, with_raw: bool = False) -> models.DataSource:
    nonce = next(_counter)
    source = models.DataSource(
        code=f"ds-del-{nonce}",
        name=f"DS Del {nonce}",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    session.add(source)
    session.flush()
    if with_raw:
        batch = models.IngestBatch(
            data_source_id=source.id,
            idempotency_key=f"key-{nonce}",
            source_type=DataSourceType.FILE_UPLOAD,
            status=IngestBatchStatus.SUBMITTED,
        )
        session.add(batch)
        session.flush()
        session.add(
            models.RawObject(
                batch_id=batch.id,
                data_source_id=source.id,
                source_type=DataSourceType.FILE_UPLOAD,
                object_uri=f"raw://{nonce}",
                checksum=f"c-{nonce}",
                status=RawObjectStatus.RAW_PERSISTED,
            )
        )
    session.commit()
    session.refresh(source)
    return source


def test_delete_unused_source_soft_deletes_and_audits(app, session):
    source = _seed_source(session)
    client = TestClient(app)
    resp = client.delete(f"/internal/v1/data-sources/{source.id}")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == DataSourceStatus.DISABLED.value
    assert body["deleted_at"]

    session.refresh(source)
    assert source.deleted_at is not None
    assert source.status == DataSourceStatus.DISABLED

    audits = list(
        session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.event_type == AuditEventType.DATA_SOURCE_DELETED
            )
        )
    )
    assert len(audits) == 1


def test_delete_unused_source_is_idempotent(app, session):
    source = _seed_source(session)
    client = TestClient(app)
    first = client.delete(f"/internal/v1/data-sources/{source.id}").json()["data"]
    second = client.delete(f"/internal/v1/data-sources/{source.id}").json()["data"]
    assert first["deleted_at"] == second["deleted_at"]


def test_delete_source_with_raw_objects_returns_409(app, session):
    source = _seed_source(session, with_raw=True)
    client = TestClient(app)
    resp = client.delete(f"/internal/v1/data-sources/{source.id}")
    assert resp.status_code == 409
    session.refresh(source)
    assert source.deleted_at is None


def test_delete_source_with_force_bypasses_dependency_check(app, session):
    source = _seed_source(session, with_raw=True)
    client = TestClient(app)
    resp = client.delete(f"/internal/v1/data-sources/{source.id}?force=true")
    assert resp.status_code == 200
    session.refresh(source)
    assert source.deleted_at is not None


def test_list_data_sources_hides_deleted_by_default(app, session):
    live = _seed_source(session)
    dead = _seed_source(session)
    client = TestClient(app)
    client.delete(f"/internal/v1/data-sources/{dead.id}")

    resp = client.get("/internal/v1/data-sources")
    ids = {row["id"] for row in resp.json()["data"]}
    assert live.id in ids
    assert dead.id not in ids

    resp_all = client.get("/internal/v1/data-sources?include_deleted=true")
    ids_all = {row["id"] for row in resp_all.json()["data"]}
    assert dead.id in ids_all


def test_delete_unknown_source_returns_404(app):
    client = TestClient(app)
    assert client.delete("/internal/v1/data-sources/nope").status_code == 404
