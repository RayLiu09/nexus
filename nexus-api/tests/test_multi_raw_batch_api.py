"""API-level tests for TP-W5-01 / TP-W5-04 batch endpoints."""

from __future__ import annotations

import base64

from nexus_api.api import v1
from nexus_app import models, services
from nexus_app.ingest import batch as ingest_batch
from nexus_app.schemas import (
    DataSourceCreate,
    DataSourceScanItem,
    DataSourceScanTaskCreate,
    IngestFileAppend,
    IngestMultiFileItem,
    IngestMultiFileSubmit,
    MultiRawBatchCreate,
)
from nexus_app.storage import InMemoryObjectStorage


def _b64(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


def _source(session):
    return services.create_data_source(
        session,
        DataSourceCreate(code="api-mrb", name="MRB", source_type="file_upload"),
    )


def test_multi_raw_batch_routes_registered(app):
    paths = {route.path for route in app.routes}
    assert "/v1/ingest/batches" in paths
    assert "/v1/ingest/batches/{batch_id}/files" in paths
    assert "/v1/ingest/files/multi" in paths


def test_create_batch_returns_open_status(monkeypatch, session, fake_request):
    source = _source(session)
    storage = InMemoryObjectStorage()
    monkeypatch.setattr(ingest_batch, "get_object_storage", lambda settings=None: storage)

    payload = MultiRawBatchCreate(
        data_source_id=source.id,
        batch_idempotency_key="bA",
        summary={"note": "open"},
    )
    result = v1.create_multi_raw_batch(payload, fake_request, session)
    assert result.data.status == "open"
    assert result.data.batch_status_detail == {}


def test_append_file_returns_queued_job(monkeypatch, session, fake_request):
    source = _source(session)
    storage = InMemoryObjectStorage()
    monkeypatch.setattr(ingest_batch, "get_object_storage", lambda settings=None: storage)

    batch_payload = MultiRawBatchCreate(
        data_source_id=source.id, batch_idempotency_key="bX"
    )
    batch = v1.create_multi_raw_batch(batch_payload, fake_request, session).data

    append_payload = IngestFileAppend(
        file_idempotency_key="f1",
        filename="one.pdf",
        content_base64=_b64(b"one"),
        content_type="application/pdf",
    )
    appended = v1.append_file_to_batch(batch.id, append_payload, fake_request, session)
    assert appended.data.job_status == "queued"
    assert appended.data.duplicate is False
    assert appended.data.file_idempotency_key == "f1"


def test_append_file_idempotent_replay(monkeypatch, session, fake_request):
    source = _source(session)
    storage = InMemoryObjectStorage()
    monkeypatch.setattr(ingest_batch, "get_object_storage", lambda settings=None: storage)

    batch = v1.create_multi_raw_batch(
        MultiRawBatchCreate(data_source_id=source.id, batch_idempotency_key="bI"),
        fake_request,
        session,
    ).data

    payload = IngestFileAppend(
        file_idempotency_key="same-key",
        filename="x.pdf",
        content_base64=_b64(b"x"),
    )
    first = v1.append_file_to_batch(batch.id, payload, fake_request, session)
    second = v1.append_file_to_batch(batch.id, payload, fake_request, session)

    assert first.data.raw_object_id == second.data.raw_object_id
    assert second.data.duplicate is True


def test_multi_submit_creates_batch_and_files(monkeypatch, session, fake_request):
    source = _source(session)
    storage = InMemoryObjectStorage()
    monkeypatch.setattr(ingest_batch, "get_object_storage", lambda settings=None: storage)

    payload = IngestMultiFileSubmit(
        data_source_id=source.id,
        batch_idempotency_key="multi-A",
        files=[
            IngestMultiFileItem(
                file_idempotency_key=f"k{i}",
                filename=f"f{i}.pdf",
                content_base64=_b64(f"body-{i}".encode()),
            )
            for i in range(3)
        ],
    )
    result = v1.submit_ingest_multi_file(payload, fake_request, session)
    assert len(result.data.items) == 3
    assert {item.file_idempotency_key for item in result.data.items} == {"k0", "k1", "k2"}
    assert all(item.job_status == "queued" for item in result.data.items)



def test_data_source_scan_task_queues_record_jobs(monkeypatch, session, fake_request):
    source = services.create_data_source(
        session,
        DataSourceCreate(
            code="api-webhook",
            name="Webhook",
            source_type="webhook",
            connection_config={"webhook_secret": "secret"},
        ),
    )
    storage = InMemoryObjectStorage()
    monkeypatch.setattr(ingest_batch, "get_object_storage", lambda settings=None: storage)

    payload = DataSourceScanTaskCreate(
        idempotency_key="scan-A",
        items=[
            DataSourceScanItem(
                item_id="evt-1",
                source_object_key="events/evt-1",
                payload={"id": "evt-1", "title": "record"},
                metadata_summary={"channel": "webhook"},
            )
        ],
    )
    result = v1.create_data_source_scan_task(source.id, payload, fake_request, session)

    assert result.data.batch.summary["scan_task"] is True
    assert result.data.items[0].job_status == "queued"
    jobs = services.list_rows(session, models.Job)
    assert jobs[0].payload["pipeline_type"] == "record"
    assert jobs[0].payload["source_object_key"] == "events/evt-1"


def test_data_source_scan_task_rejects_file_upload(session, fake_request):
    source = _source(session)
    payload = DataSourceScanTaskCreate(
        idempotency_key="scan-reject",
        items=[DataSourceScanItem(item_id="x", payload={"id": "x"})],
    )
    try:
        v1.create_data_source_scan_task(source.id, payload, fake_request, session)
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 409
    else:
        raise AssertionError("expected HTTPException 409")
