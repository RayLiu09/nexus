import base64

from nexus_app import models, pipeline, services
from nexus_app.config import get_settings
from nexus_app.enums import AssetVersionStatus, IngestBatchStatus, JobStatus, NormalizedType
from nexus_app.ingest import gateway as ingest_gateway
from nexus_app.mineru import FakeMinerUAdapter
from nexus_app.schemas import CrawlerPackageSubmit, DataSourceCreate, IngestFileSubmit
from nexus_app.storage import InMemoryObjectStorage
from nexus_app.worker.claimer import claim_jobs
from nexus_app.worker.runner import execute_job


def create_source(session, source_type="file_upload"):
    return services.create_data_source(
        session,
        DataSourceCreate(
            code=f"{source_type}-source",
            name=f"{source_type} Source",
            source_type=source_type,
        ),
    )


def run_worker(session, storage, mineru=None):
    """Claim and execute all queued jobs synchronously in the test session."""
    if mineru is None:
        mineru = FakeMinerUAdapter()
    settings = get_settings()
    jobs = claim_jobs(session, "test-worker", batch_size=10, lease_seconds=30)
    for job in jobs:
        try:
            execute_job(job, session, storage, mineru, settings)
        except Exception:
            pass


def test_file_ingest_to_document_asset_pipeline(session):
    source = create_source(session)
    storage = InMemoryObjectStorage()
    mineru = FakeMinerUAdapter()
    payload = IngestFileSubmit(
        data_source_id=source.id,
        idempotency_key="file-001",
        filename="sample.pdf",
        content_type="application/pdf",
        content_base64=base64.b64encode(b"hello mineru").decode("ascii"),
    )

    accepted = ingest_gateway.submit_file_ingest(
        session, payload, storage=storage, trace_id="trace-001"
    )
    assert accepted.job.status == JobStatus.QUEUED

    run_worker(session, storage, mineru)

    session.refresh(accepted.job)
    session.refresh(accepted.batch)
    assert accepted.job.status == JobStatus.SUCCEEDED
    assert accepted.batch.status == IngestBatchStatus.COMPLETED
    assert accepted.raw_object.object_uri.startswith("s3://nexus-test-objects/raw/")

    assets = pipeline.list_assets(session)
    assert len(assets) == 1
    versions = pipeline.list_asset_versions(session, assets[0].id)
    assert len(versions) == 1
    version = versions[0]

    assert assets[0].status == AssetVersionStatus.PROCESSING
    assert version.version_status == AssetVersionStatus.PROCESSING
    assert version.metadata_summary["m1_ready_for_governance"] is True

    artifacts = services.list_rows(session, models.ParseArtifact)
    assert len(artifacts) == 1
    assert artifacts[0].artifact_uri.startswith("s3://nexus-test-objects/parsed/")

    refs = pipeline.list_normalized_refs_for_versions(session, [version.id])
    assert len(refs) == 1
    assert refs[0].normalized_type == NormalizedType.DOCUMENT
    assert refs[0].object_uri.startswith("s3://nexus-test-objects/normalized/")

    stages = pipeline.list_job_stages(session, accepted.job.id)
    assert [s.stage_name for s in stages] == ["assetize", "parse", "normalize"]


def test_crawler_package_ingest_to_normalized_record(session):
    source = create_source(session, "crawler")
    storage = InMemoryObjectStorage()
    payload = CrawlerPackageSubmit(
        data_source_id=source.id,
        idempotency_key="crawler-001",
        package={"id": "notice-001", "title": "Program Notice", "body": "content"},
    )

    accepted = ingest_gateway.submit_crawler_package(
        session, payload, storage=storage, trace_id="trace-002"
    )
    assert accepted.job.status == JobStatus.QUEUED

    run_worker(session, storage)

    session.refresh(accepted.job)
    session.refresh(accepted.batch)
    assert accepted.job.status == JobStatus.SUCCEEDED
    assert accepted.batch.status == IngestBatchStatus.COMPLETED

    assets = pipeline.list_assets(session)
    assert len(assets) == 1
    assert assets[0].asset_kind == "record"

    versions = pipeline.list_asset_versions(session, assets[0].id)
    refs = pipeline.list_normalized_refs_for_versions(session, [versions[0].id])
    assert len(refs) == 1
    assert refs[0].normalized_type == NormalizedType.RECORD
    assert refs[0].record_count == 1

    parse_artifacts = services.list_rows(session, models.ParseArtifact)
    assert len(parse_artifacts) == 0


def test_ingest_idempotency_returns_existing_batch_without_duplicate_raw_object(session):
    source = create_source(session)
    storage = InMemoryObjectStorage()
    payload = IngestFileSubmit(
        data_source_id=source.id,
        idempotency_key="same-file",
        filename="same.pdf",
        content_base64=base64.b64encode(b"same").decode("ascii"),
    )

    first = ingest_gateway.submit_file_ingest(session, payload, storage=storage)
    second = ingest_gateway.submit_file_ingest(session, payload, storage=storage)

    assert second.batch.id == first.batch.id
    assert second.raw_object.id == first.raw_object.id
    assert len(services.list_rows(session, models.RawObject)) == 1


def test_duplicate_checksum_marks_batch_skipped_without_second_raw_object(session):
    source = create_source(session)
    storage = InMemoryObjectStorage()
    first_payload = IngestFileSubmit(
        data_source_id=source.id,
        idempotency_key="same-content-1",
        filename="same-1.pdf",
        content_base64=base64.b64encode(b"same").decode("ascii"),
    )
    second_payload = IngestFileSubmit(
        data_source_id=source.id,
        idempotency_key="same-content-2",
        filename="same-2.pdf",
        content_base64=base64.b64encode(b"same").decode("ascii"),
    )

    first = ingest_gateway.submit_file_ingest(session, first_payload, storage=storage)
    second = ingest_gateway.submit_file_ingest(session, second_payload, storage=storage)

    assert second.batch.status == IngestBatchStatus.DUPLICATE_SKIPPED
    assert second.raw_object.id == first.raw_object.id
    assert len(services.list_rows(session, models.RawObject)) == 1
    assert second.job.current_stage == "duplicate_skipped"


class FailingMinerUAdapter:
    def parse(self, filename, content, content_type=None):
        raise RuntimeError("mineru unavailable")


def test_file_ingest_failure_is_persisted_on_job_and_stage(session):
    source = create_source(session)
    storage = InMemoryObjectStorage()
    payload = IngestFileSubmit(
        data_source_id=source.id,
        idempotency_key="file-fail-001",
        filename="fail.pdf",
        content_base64=base64.b64encode(b"fail").decode("ascii"),
    )

    accepted = ingest_gateway.submit_file_ingest(session, payload, storage=storage)
    run_worker(session, storage, FailingMinerUAdapter())

    session.refresh(accepted.job)
    session.refresh(accepted.batch)
    session.refresh(accepted.raw_object)
    job = accepted.job
    batch = accepted.batch
    raw = accepted.raw_object

    versions = services.list_rows(session, models.DocumentVersion)
    stages = pipeline.list_job_stages(session, job.id)

    assert job.status == JobStatus.FAILED
    assert "RuntimeError" in (job.failure_reason or "")
    assert raw.status == "failed"
    assert batch.status == "failed"
    assert len(versions) == 1
    assert versions[0].version_status == AssetVersionStatus.FAILED
    assert versions[0].asset.status == AssetVersionStatus.FAILED
    assert stages[-1].status == JobStatus.FAILED


def test_week2_forbidden_reverse_pointers_are_not_present():
    assert not hasattr(models.DocumentAsset, "current_version_id")
    assert not hasattr(models.DocumentVersion, "normalized_ref_id")
    assert not hasattr(models.DocumentVersion, "quality_report_id")
