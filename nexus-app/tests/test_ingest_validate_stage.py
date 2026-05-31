"""Tests for the platform-level ingest_validate stage."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from nexus_app import models
from nexus_app.enums import (
    AuditEventType,
    DataSourceType,
    JobStatus,
    JobType,
    PipelineType,
    RawObjectStatus,
)
from nexus_app.ingest.config_loader import IngestValidateRegistry
from nexus_app.worker.runner import NonRetryableError, _run_ingest_validate


@pytest.fixture
def registry(tmp_path):
    cfg = tmp_path / "ingest_validate.json"
    cfg.write_text(json.dumps({
        "schema_version": "1.0",
        "mime_whitelist": ["application/pdf", "application/json"],
        "extension_whitelist": [".pdf", ".json"],
        "file_size_max_bytes": 1024,
    }))
    reg = IngestValidateRegistry()
    reg.load(str(cfg))
    return reg


def _audits(session, event_type: AuditEventType):
    return list(
        session.scalars(
            select(models.AuditLog).where(models.AuditLog.event_type == event_type)
        )
    )


_seed_counter = 0


def _seed(session, *, mime, size, filename):
    global _seed_counter
    _seed_counter += 1
    n = _seed_counter
    source = models.DataSource(
        code=f"ds-iv-{n}", name="iv", source_type=DataSourceType.FILE_UPLOAD,
    )
    session.add(source)
    session.flush()
    batch = models.IngestBatch(
        data_source_id=source.id,
        idempotency_key=f"iv-key-{n}",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    session.add(batch)
    session.flush()
    raw = models.RawObject(
        data_source_id=source.id, batch_id=batch.id,
        object_uri=f"s3://bucket/key-{n}", checksum=f"chk-{n}",
        source_type=DataSourceType.FILE_UPLOAD,
        mime_type=mime, size_bytes=size,
        status=RawObjectStatus.RAW_PERSISTED,
        metadata_summary={"filename": filename},
    )
    session.add(raw)
    session.flush()
    job = models.Job(
        job_type=JobType.INGEST_PROCESS,
        ingest_batch_id=batch.id,
        raw_object_id=raw.id,
        payload={"pipeline_type": "document"},
        status=JobStatus.RUNNING,
    )
    session.add(job)
    session.commit()
    return job, raw


class TestIngestValidateStage:
    def test_pass_all_checks(self, session, registry):
        job, raw = _seed(session, mime="application/pdf", size=500, filename="x.pdf")
        _run_ingest_validate(job, raw, session, "trace-1", PipelineType.DOCUMENT, registry=registry)
        completed = _audits(session, AuditEventType.INGEST_VALIDATE_COMPLETED)
        failed = _audits(session, AuditEventType.INGEST_VALIDATE_FAILED)
        assert completed
        assert not failed
        assert job.status == JobStatus.RUNNING

    def test_mime_not_in_whitelist(self, session, registry):
        job, raw = _seed(session, mime="application/x-msdownload", size=100, filename="evil.exe")
        with pytest.raises(NonRetryableError) as exc_info:
            _run_ingest_validate(job, raw, session, "trace-2", PipelineType.DOCUMENT, registry=registry)
        assert exc_info.value.error_code == "invalid_ingest_payload"
        failed = _audits(session, AuditEventType.INGEST_VALIDATE_FAILED)
        assert failed
        violations = failed[-1].summary["violations"]
        assert any(v["check"] == "mime_whitelist" for v in violations)
        assert any(v["check"] == "extension_whitelist" for v in violations)

    def test_size_exceeds_limit(self, session, registry):
        job, raw = _seed(session, mime="application/pdf", size=10_000, filename="big.pdf")
        with pytest.raises(NonRetryableError):
            _run_ingest_validate(job, raw, session, "trace-3", PipelineType.DOCUMENT, registry=registry)
        failed = _audits(session, AuditEventType.INGEST_VALIDATE_FAILED)
        assert failed
        violations = failed[-1].summary["violations"]
        assert any(v["check"] == "file_size_max_bytes" for v in violations)

    def test_extension_not_whitelisted(self, session, registry):
        job, raw = _seed(session, mime="application/pdf", size=100, filename="x.exe")
        with pytest.raises(NonRetryableError):
            _run_ingest_validate(job, raw, session, "trace-4", PipelineType.DOCUMENT, registry=registry)

    def test_registry_not_loaded_skips_platform_checks(self, session):
        """Unloaded registry must not break tests — only emit COMPLETED with skip marker."""
        job, raw = _seed(session, mime="any/thing", size=999_999, filename="huge.exe")
        unloaded = IngestValidateRegistry()
        _run_ingest_validate(job, raw, session, "trace-5", PipelineType.DOCUMENT, registry=unloaded)
        completed = _audits(session, AuditEventType.INGEST_VALIDATE_COMPLETED)
        assert completed
        assert completed[-1].summary.get("platform_checks") == "skipped"
