"""End-to-end integration tests for Pipeline B wave 1 (B1.1–B1.4).

Submits real or synthetic xlsx / csv bytes through the actual gateway
(`submit_file_bytes`) and then runs the worker (`execute_job`) — verifying
that the full chain (routing → ingest_validate → structured_parse →
assetize → normalize_record → governance / chunking / index skips) behaves
as the implementation plan promises.

These tests are the B1.5 deliverable. Unit-level coverage of each link in
the chain lives in:

  - tests/test_pipeline_routing.py        — B1.1 routing decision
  - tests/structured_parse/test_*.py      — B1.2 / B1.4 parser
  - tests/test_structured_parse_worker.py — B1.3 / B1.4 worker helpers

Here we only assert the cross-link contracts (Job.payload, job stages,
NormalizedAssetRef shape, Asset.asset_kind) that other tests can't easily
verify in isolation.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from nexus_app import models, services
from nexus_app.config import Settings, get_settings
from nexus_app.enums import (
    AssetKind,
    AuditEventType,
    JobStatus,
    PipelineType,
    StageStatus,
)
from nexus_app.ingest.gateway import submit_file_bytes
from nexus_app.mineru import FakeMinerUAdapter
from nexus_app.schemas import DataSourceCreate
from nexus_app.storage import InMemoryObjectStorage
from nexus_app.worker.runner import NonRetryableError, execute_job

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_JOB_DEMAND = REPO_ROOT / "docs/samples/1.（岗位需求）电子商务岗位招聘数据.xlsx"
SAMPLE_ABILITY = REPO_ROOT / "docs/samples/2.（职业能力分析）大数据技术应用专业职业能力分析表.xlsx"

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_MIME = "text/csv"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings_with_flags(*, xlsx: bool = False, csv: bool = False) -> Settings:
    """Build a Settings instance with the Pipeline B routing flags overridden.

    All other settings still load from the dev environment / .env so the
    test only diverges on the two flags under exercise.
    """
    return Settings(pipeline_b_xlsx_enabled=xlsx, pipeline_b_csv_enabled=csv)


def _create_source(session, *, code: str) -> models.DataSource:
    return services.create_data_source(
        session,
        DataSourceCreate(code=code, name=code, source_type="file_upload"),
    )


def _stage_names(session, job_id: str) -> list[str]:
    return [
        s.stage_name
        for s in session.scalars(
            select(models.JobStage).where(models.JobStage.job_id == job_id)
        )
    ]


def _audit(session, event_type: AuditEventType) -> list[models.AuditLog]:
    return list(
        session.scalars(
            select(models.AuditLog).where(models.AuditLog.event_type == event_type)
        )
    )


def _ingest_and_run(
    session,
    storage: InMemoryObjectStorage,
    *,
    content: bytes,
    filename: str,
    mime: str,
    settings: Settings,
    source_code: str,
):
    """Submit a file via the real gateway, then execute the queued job."""
    source = _create_source(session, code=source_code)
    accepted = submit_file_bytes(
        session,
        data_source_id=source.id,
        idempotency_key=f"{source_code}-key",
        content=content,
        filename=filename,
        content_type=mime,
        storage=storage,
        settings=settings,
        trace_id=f"trace-{source_code}",
    )
    # _submit_ingest commits — refresh to be safe before running the worker.
    session.refresh(accepted.job)
    execute_job(accepted.job, session, storage, FakeMinerUAdapter(), settings)
    session.refresh(accepted.job)
    return accepted


# ---------------------------------------------------------------------------
# Sample 1 — 岗位需求电子商务 xlsx (flag-on, real worksheet)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not SAMPLE_JOB_DEMAND.exists(), reason="sample missing")
class TestSampleJobDemandXlsxE2E:
    """The B1.5 acceptance scenario: ingest sample 1 xlsx with PIPELINE_B_XLSX
    enabled, verify the gateway routes it to RECORD and the worker runs
    structured_parse → assetize → normalize → governance/chunking/index skips.
    """

    @pytest.fixture
    def accepted(self, session):
        storage = InMemoryObjectStorage()
        accepted = _ingest_and_run(
            session, storage,
            content=SAMPLE_JOB_DEMAND.read_bytes(),
            filename=SAMPLE_JOB_DEMAND.name,
            mime=XLSX_MIME,
            settings=_settings_with_flags(xlsx=True),
            source_code="sample1-xlsx",
        )
        return accepted, storage

    def test_gateway_routes_xlsx_to_record_when_flag_on(self, accepted):
        acc, _ = accepted
        assert acc.job.payload["pipeline_type"] == PipelineType.RECORD.value

    def test_job_completes_successfully(self, accepted, session):
        acc, _ = accepted
        assert acc.job.status == JobStatus.SUCCEEDED, (
            f"job failed: {acc.job.failure_reason}"
        )

    def test_stage_order_starts_with_structured_parse(self, accepted, session):
        acc, _ = accepted
        names = _stage_names(session, acc.job.id)
        assert names[0] == "structured_parse"
        # downstream stages still run (even if they no-op skip)
        assert "assetize" in names
        assert "normalize" in names

    def test_asset_kind_is_record(self, accepted, session):
        acc, _ = accepted
        assert acc.batch is not None
        assets = list(session.scalars(select(models.Asset)))
        assert len(assets) == 1
        assert assets[0].asset_kind == AssetKind.RECORD

    def test_normalized_record_carries_contract_shape_record_body(self, accepted, session):
        # Post-B3.5: record_body is projected to {dataset, records} for
        # job_demand.v1 (see structured_parse/record_body_adapter.py).
        # The raw ParsedWorkbook shape no longer reaches the writer / payload;
        # parser_version / sheet structure lives on the structured_parse audit
        # event payload instead (see test_structured_parse_audit_recorded).
        acc, storage = accepted
        refs = list(session.scalars(select(models.NormalizedAssetRef)))
        assert len(refs) == 1
        ref_key = refs[0].object_uri.split("/", 3)[-1]
        import json
        payload = json.loads(storage.get_bytes(ref_key).decode("utf-8"))
        record_body = payload["record_body"]
        assert "dataset" in record_body
        assert "records" in record_body
        assert record_body["dataset"]["source_channel"] == "excel_upload"

    def test_structured_parse_audit_recorded(self, accepted, session):
        acc, _ = accepted
        audits = _audit(session, AuditEventType.STRUCTURED_PARSE_COMPLETED)
        assert len(audits) == 1
        assert audits[0].summary["format"] == "xlsx"
        assert audits[0].summary["sheet_count"] == 1


# ---------------------------------------------------------------------------
# Sample 2 — PGSD 能力分析 xlsx (multi-sheet, merged cells)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not SAMPLE_ABILITY.exists(), reason="sample missing")
class TestSampleAbilityAnalysisXlsxE2E:
    @pytest.fixture
    def accepted(self, session):
        storage = InMemoryObjectStorage()
        accepted = _ingest_and_run(
            session, storage,
            content=SAMPLE_ABILITY.read_bytes(),
            filename=SAMPLE_ABILITY.name,
            mime=XLSX_MIME,
            settings=_settings_with_flags(xlsx=True),
            source_code="sample2-xlsx",
        )
        return accepted, storage

    def test_job_succeeds(self, accepted):
        acc, _ = accepted
        assert acc.job.status == JobStatus.SUCCEEDED, (
            f"job failed: {acc.job.failure_reason}"
        )

    def test_four_pgsd_tasks_projected_in_record_body(self, accepted, session):
        # Post-B3.5: record_body is projected to {analysis, tasks} for
        # ability_analysis.pgsd.v1. The 5th sheet (overview matrix) doesn't
        # match PGSD_SHEET_NAME_PATTERN, so it's intentionally not turned
        # into a task — its evidence is consumed by profile_detect upstream.
        acc, storage = accepted
        refs = list(session.scalars(select(models.NormalizedAssetRef)))
        assert len(refs) == 1
        import json
        payload = json.loads(
            storage.get_bytes(refs[0].object_uri.split("/", 3)[-1]).decode("utf-8")
        )
        record_body = payload["record_body"]
        assert record_body["analysis"]["analysis_model"] == "PGSD"
        task_codes = sorted(t["task_code"] for t in record_body["tasks"])
        assert task_codes == ["1", "2", "3", "4"]
        # Order-agnostic — Chinese sort order differs from intuition.
        task_names = {t["task_name"] for t in record_body["tasks"]}
        assert task_names == {"数据采集", "数据标注", "数据ETL处理", "可视化图表制作"}

    def test_p_category_abilities_grouped_under_work_contents(self, accepted, session):
        # The projector buckets P-x.y.z codes under work_content x.y, while
        # G/S/D codes drop into the task's general_abilities map. Verify both
        # paths fire on the sample data.
        acc, storage = accepted
        refs = list(session.scalars(select(models.NormalizedAssetRef)))
        import json
        payload = json.loads(
            storage.get_bytes(refs[0].object_uri.split("/", 3)[-1]).decode("utf-8")
        )
        task1 = next(t for t in payload["record_body"]["tasks"] if t["task_code"] == "1")
        # At least one work_content with at least one P ability under it.
        assert task1["work_contents"]
        wc = task1["work_contents"][0]
        assert wc["abilities"]
        first_p = wc["abilities"][0]
        assert first_p["ability_code"].startswith("P-")
        assert first_p["ability_major_category_code"] == "P"
        # G/S/D map is always declared even when empty.
        assert set(task1["general_abilities"].keys()) == {"G", "S", "D"}


# ---------------------------------------------------------------------------
# Flag-off — xlsx still routes to DOCUMENT (B1.1 invariant)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not SAMPLE_JOB_DEMAND.exists(), reason="sample missing")
class TestXlsxFlagOffStaysOnDocumentPipeline:
    def test_gateway_routes_xlsx_to_document_when_flag_off(self, session):
        storage = InMemoryObjectStorage()
        source = _create_source(session, code="xlsx-flag-off")
        accepted = submit_file_bytes(
            session,
            data_source_id=source.id,
            idempotency_key="xlsx-flag-off-key",
            content=SAMPLE_JOB_DEMAND.read_bytes(),
            filename=SAMPLE_JOB_DEMAND.name,
            content_type=XLSX_MIME,
            storage=storage,
            settings=_settings_with_flags(xlsx=False),  # explicit off
            trace_id="trace-flag-off",
        )
        # Only the routing decision matters here; we do NOT run the worker
        # because the document pipeline needs MinerU mocking that's already
        # covered in test_week2_pipeline.
        assert accepted.job.payload["pipeline_type"] == PipelineType.DOCUMENT.value


# ---------------------------------------------------------------------------
# csv — synthetic small dataset (B1.4 worker integration)
# ---------------------------------------------------------------------------


class TestCsvE2E:
    def test_csv_with_flag_on_runs_record_pipeline(self, session):
        storage = InMemoryObjectStorage()
        accepted = _ingest_and_run(
            session, storage,
            content=b"name,city\nzhang,beijing\nli,shanghai\n",
            filename="recruits.csv",
            mime=CSV_MIME,
            settings=_settings_with_flags(csv=True),
            source_code="csv-flag-on",
        )
        assert accepted.job.payload["pipeline_type"] == PipelineType.RECORD.value
        assert accepted.job.status == JobStatus.SUCCEEDED, (
            f"job failed: {accepted.job.failure_reason}"
        )

        # structured_parse stage uses the csv parser
        stages = list(
            session.scalars(
                select(models.JobStage).where(
                    models.JobStage.job_id == accepted.job.id,
                    models.JobStage.stage_name == "structured_parse",
                )
            )
        )
        assert len(stages) == 1
        assert stages[0].detail["format"] == "csv"
        assert stages[0].detail["parser_version"] == "csv_parser.v1"

    def test_csv_with_flag_off_routes_to_document_pipeline(self, session):
        storage = InMemoryObjectStorage()
        source = _create_source(session, code="csv-flag-off")
        accepted = submit_file_bytes(
            session,
            data_source_id=source.id,
            idempotency_key="csv-flag-off-key",
            content=b"a,b\n1,2",
            filename="x.csv",
            content_type=CSV_MIME,
            storage=storage,
            settings=_settings_with_flags(csv=False),
            trace_id="trace-csv-off",
        )
        assert accepted.job.payload["pipeline_type"] == PipelineType.DOCUMENT.value


# ---------------------------------------------------------------------------
# Corrupt source — must fail loudly via the structured_parse_corrupt_source
# error code, not silently succeed.
# ---------------------------------------------------------------------------


class TestCorruptXlsxE2E:
    def test_corrupt_xlsx_bytes_fail_job_with_structured_parse_error(self, session):
        storage = InMemoryObjectStorage()
        source = _create_source(session, code="corrupt-xlsx")
        accepted = submit_file_bytes(
            session,
            data_source_id=source.id,
            idempotency_key="corrupt-key",
            content=b"NOT a real xlsx zip",
            filename="bad.xlsx",
            content_type=XLSX_MIME,
            storage=storage,
            settings=_settings_with_flags(xlsx=True),
            trace_id="trace-corrupt",
        )

        with pytest.raises(NonRetryableError) as excinfo:
            execute_job(
                accepted.job,
                session,
                storage,
                FakeMinerUAdapter(),
                _settings_with_flags(xlsx=True),
            )
        assert excinfo.value.error_code == "structured_parse_corrupt_source"

        session.refresh(accepted.job)
        assert accepted.job.status == JobStatus.FAILED
        assert accepted.job.last_error_code == "structured_parse_corrupt_source"

        # The structured_parse stage row exists and is FAILED
        sp_stages = list(
            session.scalars(
                select(models.JobStage).where(
                    models.JobStage.job_id == accepted.job.id,
                    models.JobStage.stage_name == "structured_parse",
                )
            )
        )
        assert len(sp_stages) == 1
        assert sp_stages[0].status == StageStatus.FAILED
