from datetime import datetime, timedelta, timezone

from nexus_api.api.internal.system import build_workbench_summary, workbench_summary
from nexus_app import models
from nexus_app.enums import (
    AIGovernanceRunAdoptionStatus,
    AIGovernanceRunValidationStatus,
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    IngestBatchStatus,
    JobStatus,
    JobType,
    GovernanceResultStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
)


def _seed_workbench_data(session) -> None:
    source = models.DataSource(
        id="source-workbench",
        code="source-workbench",
        name="Workbench source",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    session.add(source)
    base_time = datetime(2026, 9, 1, tzinfo=timezone.utc)

    for index in range(25):
        batch = models.IngestBatch(
            id=f"batch-{index:02d}",
            data_source_id=source.id,
            idempotency_key=f"workbench-{index:02d}",
            source_type=DataSourceType.FILE_UPLOAD,
            status=(
                IngestBatchStatus.PROCESSING
                if index < 3
                else IngestBatchStatus.COMPLETED
            ),
        )
        raw = models.RawObject(
            id=f"raw-{index:02d}",
            batch_id=batch.id,
            data_source_id=source.id,
            source_type=DataSourceType.FILE_UPLOAD,
            object_uri=f"raw/workbench-{index:02d}.pdf",
            checksum=f"raw-checksum-{index:02d}",
            status=RawObjectStatus.RAW_PERSISTED,
        )
        asset = models.Asset(
            id=f"asset-{index:02d}",
            data_source_id=source.id,
            source_object_key=f"workbench-{index:02d}.pdf",
            title=f"Workbench asset {index:02d}",
            asset_kind=AssetKind.DOCUMENT,
            status=(
                AssetVersionStatus.DISABLED
                if index == 24
                else AssetVersionStatus.AVAILABLE
            ),
        )
        version = models.AssetVersion(
            id=f"version-{index:02d}",
            asset_id=asset.id,
            raw_object_id=raw.id,
            version_no=1,
            version_status=asset.status,
            source_checksum=raw.checksum,
        )
        normalized_ref = models.NormalizedAssetRef(
            id=f"ref-{index:02d}",
            version_id=version.id,
            normalized_type=NormalizedType.DOCUMENT,
            object_uri=f"normalized/workbench-{index:02d}.json",
            schema_version="1.0",
            checksum=f"ref-checksum-{index:02d}",
            status=NormalizedAssetRefStatus.GENERATED,
        )

        if index < 18:
            job_status = JobStatus.SUCCEEDED
        elif index < 20:
            job_status = JobStatus.FAILED
        elif index == 20:
            job_status = JobStatus.DEAD_LETTERED
        elif index < 23:
            job_status = JobStatus.RUNNING
        else:
            job_status = JobStatus.QUEUED
        job = models.Job(
            id=f"job-{index:02d}",
            job_type=JobType.INGEST_PROCESS,
            status=job_status,
            ingest_batch_id=batch.id,
            raw_object_id=raw.id,
            idempotency_key=f"job-workbench-{index:02d}",
        )

        if index < 10:
            adoption_status = AIGovernanceRunAdoptionStatus.AUTO_ADOPTED
            quality_score = 90
        elif index < 18:
            adoption_status = AIGovernanceRunAdoptionStatus.REVIEW_REQUIRED
            quality_score = 70
        elif index < 21:
            adoption_status = AIGovernanceRunAdoptionStatus.PENDING_RULE_GUARDRAIL
            quality_score = 50
        else:
            adoption_status = AIGovernanceRunAdoptionStatus.REJECTED
            quality_score = 50
        run_time = base_time + timedelta(minutes=index)
        run = models.AIGovernanceRun(
            id=f"run-{index:02d}",
            normalized_ref_id=normalized_ref.id,
            model_alias="governance-model",
            prompt_version="v1",
            input_hash=f"input-{index:02d}",
            quality_summary={"quality_score": quality_score},
            validation_status=AIGovernanceRunValidationStatus.SCHEMA_VALID,
            adoption_status=adoption_status,
            created_at=run_time,
            updated_at=run_time,
        )
        if index < 10:
            result_status = GovernanceResultStatus.AVAILABLE
        elif index < 21:
            result_status = GovernanceResultStatus.REVIEW_REQUIRED
        else:
            result_status = GovernanceResultStatus.DISABLED
        result = models.GovernanceResult(
            id=f"result-{index:02d}",
            normalized_ref_id=normalized_ref.id,
            ai_run_id=run.id,
            status=result_status,
            quality_summary={"quality_score": quality_score},
            created_at=run_time,
            updated_at=run_time,
        )

        session.add_all([batch, raw, asset, version, normalized_ref, job, run, result])

    session.add(
        models.AIGovernanceRun(
            id="run-00-historical-review",
            normalized_ref_id="ref-00",
            model_alias="governance-model",
            prompt_version="v0",
            input_hash="input-00-historical",
            quality_summary={"quality_score": 20},
            validation_status=AIGovernanceRunValidationStatus.SCHEMA_VALID,
            adoption_status=AIGovernanceRunAdoptionStatus.REVIEW_REQUIRED,
            created_at=base_time - timedelta(days=1),
            updated_at=base_time - timedelta(days=1),
        )
    )
    session.add(
        models.GovernanceResult(
            id="result-00-historical-review",
            normalized_ref_id="ref-00",
            ai_run_id="run-00-historical-review",
            status=GovernanceResultStatus.REVIEW_REQUIRED,
            created_at=base_time - timedelta(days=1),
            updated_at=base_time - timedelta(days=1),
        )
    )
    session.commit()


def test_workbench_summary_uses_all_rows_beyond_default_page(session):
    _seed_workbench_data(session)

    summary = build_workbench_summary(session)

    assert summary.asset_count == 24
    assert summary.normalized_ref_count == 25
    assert summary.raw_object_count == 25
    assert summary.ingest_batch_count == 25
    assert summary.processing_batches == 3
    assert summary.job_count == 25
    assert summary.succeeded_jobs == 18
    assert summary.failed_jobs == 3
    assert summary.running_jobs == 4
    assert summary.pipeline_health == 86
    assert summary.governed_ref_count == 25
    assert summary.governance_coverage == 100
    assert summary.auto_adopted == 10
    assert summary.review_required == 11
    assert summary.quality_pass == 10
    assert summary.quality_warning == 8
    assert summary.quality_fail == 7
    assert summary.avg_quality == 72
    assert len(summary.review_items) == 5
    assert all(item.adoption_status == "review_required" for item in summary.review_items)
    assert "result-00-historical-review" not in {item.id for item in summary.review_items}


def test_workbench_summary_endpoint_uses_standard_envelope(session, fake_request):
    payload = workbench_summary(fake_request, session)

    assert payload.data.pipeline_health == 100
    assert payload.data.asset_count == 0
    assert payload.data.review_items == []
    assert payload.meta.trace_id == "trace-test-001"
