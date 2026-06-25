"""End-to-end coverage for B4: real xlsx sample → pipeline → writer.

Two scenarios:

1. **Pipeline current state (no upstream adapter yet)** — B1 dumps the
   ParsedWorkbook directly into `record_body`. The B4 writer cannot consume
   that shape (it expects `{dataset, records}` per §5.0.2), so the dispatcher
   reports `record_body_shape_invalid` and the rest of the pipeline keeps
   moving. This test exists to prove B4 doesn't break the existing B1→B3
   chain that landed in earlier slices.

2. **Synthetic contract-shaped payload** — we hand-craft a `{dataset, records}`
   record_body and overwrite the MinIO payload, then re-run
   `dispatch_domain_normalize`. This proves the B4 writer is wired correctly
   and lands data in `job_demand_dataset` + `job_demand_record`. Once the
   structured_parse → record_body adapter ships, scenario 1's expected
   outcome becomes scenario 2's outcome.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from nexus_app import models, services
from nexus_app.config import Settings
from nexus_app.domain_normalize import dispatch_domain_normalize
from nexus_app.enums import (
    AuditEventType,
    JobStatus,
    NormalizedType,
)
from nexus_app.ingest.gateway import submit_file_bytes
from nexus_app.mineru import FakeMinerUAdapter
from nexus_app.schemas import DataSourceCreate
from nexus_app.storage import InMemoryObjectStorage
from nexus_app.worker.runner import execute_job

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_JOB_DEMAND = REPO_ROOT / "docs/samples/1.（岗位需求）电子商务岗位招聘数据.xlsx"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.mark.skipif(not SAMPLE_JOB_DEMAND.exists(), reason="sample xlsx missing")
class TestSampleXlsxThroughPipeline:
    """Run the real B1 → B2 → B3 → B4 chain on sample 1."""

    @pytest.fixture
    def pipeline_run(self, session):
        storage = InMemoryObjectStorage()
        source = services.create_data_source(
            session,
            DataSourceCreate(
                code="b4-sample1", name="b4-sample1", source_type="file_upload",
            ),
        )
        accepted = submit_file_bytes(
            session,
            data_source_id=source.id,
            idempotency_key="b4-sample1-key",
            content=SAMPLE_JOB_DEMAND.read_bytes(),
            filename=SAMPLE_JOB_DEMAND.name,
            content_type=XLSX_MIME,
            storage=storage,
            settings=Settings(pipeline_b_xlsx_enabled=True),
            trace_id="trace-b4-sample1",
        )
        session.refresh(accepted.job)
        execute_job(
            accepted.job,
            session,
            storage,
            FakeMinerUAdapter(),
            Settings(pipeline_b_xlsx_enabled=True),
        )
        session.refresh(accepted.job)
        return accepted.job, storage

    def test_job_completes_without_crashing_on_b4(self, pipeline_run, session):
        # Even though the current B1→B3 chain dumps a ParsedWorkbook into
        # record_body, the B4 writer must NOT raise — it skips gracefully so
        # downstream governance keeps working.
        job, _storage = pipeline_run
        assert job.status == JobStatus.SUCCEEDED, (
            f"job failed unexpectedly: {job.failure_reason}"
        )

    def test_normalized_ref_persisted(self, pipeline_run, session):
        job, _ = pipeline_run
        ref = next(iter(session.scalars(select(models.NormalizedAssetRef))))
        assert ref is not None
        assert ref.normalized_type == NormalizedType.RECORD

    def test_no_job_demand_dataset_when_record_body_shape_invalid(self, pipeline_run, session):
        # B1 currently emits ParsedWorkbook dump → no {dataset, records}
        # wrapper → writer skips. Until the structured_parse → record_body
        # adapter lands (post-B4), there should be ZERO rows in B4 tables.
        _, _ = pipeline_run
        assert session.scalar(select(models.JobDemandDataset)) is None
        assert session.scalar(select(models.JobDemandRecord)) is None

    def test_domain_normalize_audit_event_emitted_with_skipped_reason(
        self, pipeline_run, session
    ):
        # `_run_domain_normalize` (worker) wraps dispatcher result into the
        # DOMAIN_NORMALIZE_COMPLETED event with `skipped` + `reason`. We
        # expect to see a record_body_shape_invalid skip, NOT a failure.
        _, _ = pipeline_run
        events = list(
            session.scalars(
                select(models.AuditLog).where(
                    models.AuditLog.event_type == AuditEventType.DOMAIN_NORMALIZE_COMPLETED
                )
            ).all()
        )
        assert events
        summary = events[-1].summary
        assert summary["domain_profile"] == "job_demand.v1"
        assert summary["skipped"] is True
        assert summary["reason"] == "record_body_shape_invalid"


@pytest.mark.skipif(not SAMPLE_JOB_DEMAND.exists(), reason="sample xlsx missing")
class TestSyntheticContractShapedPayload:
    """Hand-craft a B4-contract-shaped record_body atop the real sample and
    prove the writer lands data when the upstream adapter eventually ships."""

    @pytest.fixture
    def primed(self, session):
        storage = InMemoryObjectStorage()
        source = services.create_data_source(
            session,
            DataSourceCreate(
                code="b4-sample1-synthetic", name="b4-sample1-synthetic",
                source_type="file_upload",
            ),
        )
        accepted = submit_file_bytes(
            session,
            data_source_id=source.id,
            idempotency_key="b4-sample1-synth-key",
            content=SAMPLE_JOB_DEMAND.read_bytes(),
            filename=SAMPLE_JOB_DEMAND.name,
            content_type=XLSX_MIME,
            storage=storage,
            settings=Settings(pipeline_b_xlsx_enabled=True),
            trace_id="trace-b4-synth",
        )
        session.refresh(accepted.job)
        execute_job(
            accepted.job,
            session,
            storage,
            FakeMinerUAdapter(),
            Settings(pipeline_b_xlsx_enabled=True),
        )
        session.refresh(accepted.job)

        ref = next(iter(session.scalars(select(models.NormalizedAssetRef))))

        # Overwrite the MinIO payload with a contract-shaped record_body so
        # the writer can consume it. The synthetic dataset has 3 records,
        # one duplicate, one placeholder.
        key = ref.object_uri.split("/", 3)[-1]
        contract_payload = {
            "schema_version": "normalized-record.v2",
            "domain_profile": "job_demand.v1",
            "record_body": {
                "dataset": {
                    "major_name": "电子商务",
                    "industry_name": "互联网",
                    "source_channel": "excel_upload",
                    "record_count": 4,
                    "invalid_count": 1,
                    "duplicate_count": 1,
                },
                "records": [
                    {
                        "source_record_key": "Sheet1#row2",
                        "job_title": "数据分析师",
                        "company_name": "ACME",
                        "city": "上海",
                        "salary_min": 4000,
                        "salary_max": 7000,
                        "enterprise_size": "20-99人",
                        "trace": {"sheet": "Sheet1", "row": 2},
                    },
                    {
                        "source_record_key": "Sheet1#row3",
                        "job_title": "后端工程师",
                        "company_name": "BAR Co",
                        "city": "北京",
                        "enterprise_size": "100-499人",
                        "trace": {"sheet": "Sheet1", "row": 3},
                    },
                    # Duplicate of row 2 by fingerprint.
                    {
                        "source_record_key": "Sheet1#row2",
                        "job_title": "数据分析师",
                        "company_name": "ACME",
                        "city": "上海",
                        "trace": {"sheet": "Sheet1", "row": 99},
                    },
                    # Placeholder row.
                    {
                        "source_record_key": "Sheet1#row4",
                        "job_title": "...",
                        "trace": {"sheet": "Sheet1", "row": 4},
                    },
                ],
            },
        }
        storage.put_bytes(
            key,
            json.dumps(contract_payload).encode("utf-8"),
            "application/json",
        )
        return ref, storage

    def test_writer_lands_synthetic_dataset(self, primed, session):
        ref, storage = primed
        result = dispatch_domain_normalize(session, ref, storage=storage)
        session.commit()

        assert result.skipped is False
        assert result.domain_profile == "job_demand.v1"
        assert result.dataset_id is not None
        assert result.records_written == 2  # 4 - 1 duplicate - 1 placeholder

        dataset = session.scalar(select(models.JobDemandDataset))
        assert dataset is not None
        assert dataset.record_count == 4
        assert dataset.duplicate_count == 1
        assert dataset.invalid_count == 1
        assert dataset.quality_summary.get("duplicate_fingerprint") == 1
        assert dataset.quality_summary.get("placeholder_row_dropped") == 1

    def test_writer_persists_correct_records(self, primed, session):
        ref, storage = primed
        dispatch_domain_normalize(session, ref, storage=storage)
        session.commit()
        rows = list(session.scalars(select(models.JobDemandRecord)).all())
        keys = {r.source_record_key for r in rows}
        assert keys == {"Sheet1#row2", "Sheet1#row3"}
        # Verify mapped fields are present (sanity check on field mapping).
        first = next(r for r in rows if r.source_record_key == "Sheet1#row2")
        assert first.job_title == "数据分析师"
        assert first.company_name == "ACME"
        assert first.enterprise_size == "20-99人"

    def test_audit_events_written(self, primed, session):
        ref, storage = primed
        dispatch_domain_normalize(session, ref, storage=storage)
        session.commit()
        dataset_event = session.scalar(
            select(models.AuditLog).where(
                models.AuditLog.event_type == AuditEventType.JOB_DEMAND_DATASET_PERSISTED
            )
        )
        records_event = session.scalar(
            select(models.AuditLog).where(
                models.AuditLog.event_type == AuditEventType.JOB_DEMAND_RECORDS_PERSISTED
            )
        )
        assert dataset_event is not None
        assert records_event is not None
        assert records_event.summary["records_inserted"] == 2
