import base64
from io import BytesIO

from nexus_api.api import internal as v1
from nexus_app import models, services
from nexus_app.ingest import gateway as ingest_gateway
from nexus_app.schemas import CrawlerPackageSubmit, DataSourceCreate, IngestFileSubmit
from nexus_app.storage import InMemoryObjectStorage


def create_source(session, source_type="file_upload"):
    return services.create_data_source(
        session,
        DataSourceCreate(
            code=f"api-{source_type}",
            name=f"API {source_type}",
            source_type=source_type,
        ),
    )


def test_week2_routes_are_registered(app):
    paths = {route.path for route in app.routes}

    assert "/internal/v1/ingest/files" in paths
    assert "/internal/v1/ingest/files/upload" in paths
    assert "/internal/v1/ingest/crawler-packages" in paths
    assert "/internal/v1/jobs" in paths
    assert "/internal/v1/jobs/{job_id}/stages" in paths
    assert "/internal/v1/assets" in paths
    assert "/internal/v1/assets/{asset_id}" in paths
    assert "/internal/v1/assets/{asset_id}/versions" in paths
    assert "/internal/v1/normalized-refs" in paths
    assert "/internal/v1/parse-artifacts" in paths
    assert "/internal/v1/audit-logs" in paths
    assert "/internal/v1/ingest/batches/{batch_id}/raw-objects" in paths
    assert "/internal/v1/raw-objects" not in {
        route.path for route in app.routes if "POST" in getattr(route, "methods", set())
    }


def test_submit_file_route_returns_queued_job(monkeypatch, session, fake_request):
    source = create_source(session)
    storage = InMemoryObjectStorage()
    monkeypatch.setattr(ingest_gateway, "get_object_storage", lambda settings=None: storage)
    payload = IngestFileSubmit(
        data_source_id=source.id,
        idempotency_key="api-file-001",
        filename="api.pdf",
        content_base64=base64.b64encode(b"api file").decode("ascii"),
    )

    result = v1.submit_ingest_file(payload, fake_request, session)

    assert result.data.job.status == "queued"
    assert result.data.batch.status == "raw_persisted"
    assert result.data.raw_object.object_uri.startswith("s3://nexus-test-objects/raw/")


def test_submit_crawler_route_returns_queued_job(monkeypatch, session, fake_request):
    source = create_source(session, "crawler")
    storage = InMemoryObjectStorage()
    monkeypatch.setattr(ingest_gateway, "get_object_storage", lambda settings=None: storage)
    payload = CrawlerPackageSubmit(
        data_source_id=source.id,
        idempotency_key="api-crawler-001",
        package={"id": "record-001", "title": "Record title"},
    )

    result = v1.submit_crawler_package(payload, fake_request, session)

    assert result.data.job.status == "queued"
    assert result.data.batch.status == "raw_persisted"
    assert result.data.raw_object.object_uri.startswith("s3://nexus-test-objects/raw/")
    assert services.list_rows(session, models.RawObject)[0].id == result.data.raw_object.id


def test_submit_file_upload_multipart_returns_queued_job(monkeypatch, session, fake_request):
    """Test multipart file upload endpoint (for large files or browser uploads)."""
    import asyncio

    from fastapi import UploadFile

    source = create_source(session)
    storage = InMemoryObjectStorage()
    monkeypatch.setattr(ingest_gateway, "get_object_storage", lambda settings=None: storage)

    file_content = b"multipart file content"
    file_obj = BytesIO(file_content)
    upload_file = UploadFile(filename="multipart.pdf", file=file_obj)
    # Manually set headers to simulate content_type
    upload_file.headers = {"content-type": "application/pdf"}

    result = asyncio.run(
        v1.submit_ingest_file_upload(
            data_source_id=source.id,
            idempotency_key="api-multipart-001",
            file=upload_file,
            source_uri=None,
            owner_user_id=None,
            request=fake_request,
            session=session,
        )
    )

    assert result.data.job.status == "queued"
    assert result.data.batch.status == "raw_persisted"
    assert result.data.raw_object.object_uri.startswith("s3://nexus-test-objects/raw/")
    assert result.data.raw_object.mime_type == "application/pdf"

    raw_objects = services.list_rows(session, models.RawObject)
    assert len(raw_objects) == 1
    assert raw_objects[0].metadata_summary["filename"] == "multipart.pdf"
