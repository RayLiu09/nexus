import base64

from nexus_api.api import v1
from nexus_app import models, services
from nexus_app.mineru import FakeMinerUAdapter
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

    assert "/v1/ingest/files" in paths
    assert "/v1/ingest/crawler-packages" in paths
    assert "/v1/jobs" in paths
    assert "/v1/jobs/{job_id}/stages" in paths
    assert "/v1/assets" in paths
    assert "/v1/assets/{asset_id}" in paths
    assert "/v1/assets/{asset_id}/versions" in paths
    assert "/v1/normalized-refs" in paths
    assert "/v1/parse-artifacts" in paths


def test_submit_file_route_returns_ingest_to_asset_result(monkeypatch, session, fake_request):
    source = create_source(session)
    storage = InMemoryObjectStorage()
    monkeypatch.setattr(v1.pipeline, "get_object_storage", lambda settings=None: storage)
    monkeypatch.setattr(v1.pipeline, "get_mineru_adapter", lambda settings=None: FakeMinerUAdapter())
    payload = IngestFileSubmit(
        data_source_id=source.id,
        idempotency_key="api-file-001",
        filename="api.pdf",
        content_base64=base64.b64encode(b"api file").decode("ascii"),
    )

    result = v1.submit_ingest_file(payload, fake_request, session)

    assert result.data.batch.status == "completed"
    assert result.data.asset.status == "available"
    assert result.data.version.version_status == "available"
    assert result.data.normalized_ref.normalized_type == "document"


def test_submit_crawler_route_creates_record_asset(monkeypatch, session, fake_request):
    source = create_source(session, "crawler")
    storage = InMemoryObjectStorage()
    monkeypatch.setattr(v1.pipeline, "get_object_storage", lambda settings=None: storage)
    payload = CrawlerPackageSubmit(
        data_source_id=source.id,
        idempotency_key="api-crawler-001",
        package={"id": "record-001", "title": "Record title"},
    )

    result = v1.submit_crawler_package(payload, fake_request, session)

    assert result.data.asset.asset_kind == "record"
    assert result.data.parse_artifact is None
    assert result.data.normalized_ref.normalized_type == "record"
    assert services.list_rows(session, models.DocumentAsset)[0].id == result.data.asset.id
