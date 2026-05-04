import base64

from nexus_app import models, pipeline, services
from nexus_app.enums import AssetVersionStatus, NormalizedType
from nexus_app.mineru import FakeMinerUAdapter
from nexus_app.schemas import CrawlerPackageSubmit, DataSourceCreate, IngestFileSubmit
from nexus_app.storage import InMemoryObjectStorage


def create_source(session, source_type="file_upload"):
    return services.create_data_source(
        session,
        DataSourceCreate(
            code=f"{source_type}-source",
            name=f"{source_type} Source",
            source_type=source_type,
        ),
    )


def test_file_ingest_to_document_asset_pipeline(session):
    source = create_source(session)
    storage = InMemoryObjectStorage()
    payload = IngestFileSubmit(
        data_source_id=source.id,
        idempotency_key="file-001",
        filename="sample.pdf",
        content_type="application/pdf",
        content_base64=base64.b64encode(b"hello mineru").decode("ascii"),
    )

    result = pipeline.submit_file_ingest(
        session, payload, storage=storage, mineru=FakeMinerUAdapter(), trace_id="trace-001"
    )

    assert result.batch.status == "completed"
    assert result.raw_object.object_uri.startswith("s3://nexus-test-objects/raw/")
    assert result.job.status == "succeeded"
    assert result.asset.status == AssetVersionStatus.AVAILABLE
    assert result.version.version_status == AssetVersionStatus.AVAILABLE
    assert result.parse_artifact.artifact_uri.startswith("s3://nexus-test-objects/parsed/")
    assert result.normalized_ref.normalized_type == NormalizedType.DOCUMENT
    assert result.normalized_ref.object_uri.startswith("s3://nexus-test-objects/normalized/")

    stages = pipeline.list_job_stages(session, result.job.id)
    assert [stage.stage_name for stage in stages] == ["assetize", "parse", "normalize"]


def test_crawler_package_ingest_to_normalized_record(session):
    source = create_source(session, "crawler")
    storage = InMemoryObjectStorage()
    payload = CrawlerPackageSubmit(
        data_source_id=source.id,
        idempotency_key="crawler-001",
        package={"id": "notice-001", "title": "Program Notice", "body": "content"},
    )

    result = pipeline.submit_crawler_package(session, payload, storage=storage, trace_id="trace-002")

    assert result.batch.status == "completed"
    assert result.parse_artifact is None
    assert result.asset.asset_kind == "record"
    assert result.normalized_ref.normalized_type == NormalizedType.RECORD
    assert result.normalized_ref.record_count == 1


def test_ingest_idempotency_returns_existing_batch_without_duplicate_raw_object(session):
    source = create_source(session)
    storage = InMemoryObjectStorage()
    payload = IngestFileSubmit(
        data_source_id=source.id,
        idempotency_key="same-file",
        filename="same.pdf",
        content_base64=base64.b64encode(b"same").decode("ascii"),
    )

    first = pipeline.submit_file_ingest(session, payload, storage=storage, mineru=FakeMinerUAdapter())
    second = pipeline.submit_file_ingest(session, payload, storage=storage, mineru=FakeMinerUAdapter())

    assert second.batch.id == first.batch.id
    assert second.raw_object.id == first.raw_object.id
    assert len(services.list_rows(session, models.RawObject)) == 1


def test_week2_forbidden_reverse_pointers_are_not_present():
    assert not hasattr(models.DocumentAsset, "current_version_id")
    assert not hasattr(models.DocumentVersion, "normalized_ref_id")
    assert not hasattr(models.DocumentVersion, "quality_report_id")
