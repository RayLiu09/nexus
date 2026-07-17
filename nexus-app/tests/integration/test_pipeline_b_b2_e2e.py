"""End-to-end integration tests for Pipeline B wave 2 (profile_detect, B2.x).

Layered on top of the B1 e2e:

  - tests/integration/test_pipeline_b_b1_e2e.py — routing + structured_parse
    + worker integration (parser → normalized_record).
  - this file — adds profile_detect assertions: detector output landed in
    normalized_record + metadata_summary, audit events fired correctly,
    AssetVersion parked in REVIEW_REQUIRED only for candidates / generic /
    low-confidence detections.

These tests submit through the real gateway (`submit_file_bytes`) — they're
the canonical "flag-on demo" of the full chain after B2.3 lands.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from nexus_app import models, services
from nexus_app.config import Settings
from nexus_app.enums import (
    AssetVersionStatus,
    AuditEventType,
    JobStatus,
    PipelineType,
)
from nexus_app.ingest.gateway import submit_file_bytes
from nexus_app.mineru import FakeMinerUAdapter
from nexus_app.profile_detect import DEFAULT_AUTO_ADMIT_THRESHOLD
from nexus_app.schemas import DataSourceCreate
from nexus_app.storage import InMemoryObjectStorage
from nexus_app.worker.runner import execute_job

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_JOB_DEMAND = REPO_ROOT / "docs/samples/1.（岗位需求）电子商务岗位招聘数据.xlsx"
SAMPLE_ABILITY = REPO_ROOT / "docs/samples/2.（职业能力分析）大数据技术应用专业职业能力分析表.xlsx"

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_MIME = "text/csv"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings_with_flags(*, xlsx: bool = False, csv: bool = False) -> Settings:
    return Settings(pipeline_b_xlsx_enabled=xlsx, pipeline_b_csv_enabled=csv)


def _create_source(session, *, code: str):
    return services.create_data_source(
        session,
        DataSourceCreate(code=code, name=code, source_type="file_upload"),
    )


def _audits(session, event_type: AuditEventType) -> list[models.AuditLog]:
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
    """Submit through the real gateway and run the worker."""
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
    session.refresh(accepted.job)
    execute_job(accepted.job, session, storage, FakeMinerUAdapter(), settings)
    session.refresh(accepted.job)
    return accepted


def _normalized_ref(session) -> models.NormalizedAssetRef:
    refs = list(session.scalars(select(models.NormalizedAssetRef)))
    assert len(refs) == 1, f"expected exactly one NormalizedAssetRef, got {len(refs)}"
    return refs[0]


def _normalized_payload(storage: InMemoryObjectStorage, ref: models.NormalizedAssetRef) -> dict:
    """Fetch the MinIO-side normalized_record JSON payload."""
    key = ref.object_uri.split("/", 3)[-1]
    return json.loads(storage.get_bytes(key).decode("utf-8"))


def _build_xlsx(builder) -> bytes:
    wb = Workbook()
    builder(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Sample 1 — 岗位需求 xlsx (high confidence, canonical)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not SAMPLE_JOB_DEMAND.exists(), reason="sample missing")
class TestSample1ProfileDetectE2E:
    @pytest.fixture
    def state(self, session):
        storage = InMemoryObjectStorage()
        accepted = _ingest_and_run(
            session, storage,
            content=SAMPLE_JOB_DEMAND.read_bytes(),
            filename=SAMPLE_JOB_DEMAND.name,
            mime=XLSX_MIME,
            settings=_settings_with_flags(xlsx=True),
            source_code="b24-sample1",
        )
        return accepted, storage

    def test_job_succeeded(self, state):
        accepted, _ = state
        assert accepted.job.status == JobStatus.SUCCEEDED, (
            f"job failed: {accepted.job.failure_reason}"
        )

    def test_profile_detected_as_canonical_job_demand(self, state, session):
        _, storage = state
        ref = _normalized_ref(session)
        profile = ref.metadata_summary.get("profile")
        assert profile is not None, "profile must be mirrored into metadata_summary"
        assert profile["record_type"] == "job_demand_dataset"
        assert profile["domain"] == "occupation"
        assert profile["domain_profile"] == "job_demand.v1"
        # `_run_record_pipeline` serialises the profile via
        # `model_dump(mode="json", exclude_none=True)` (see
        # worker/runner.py:1748), so an optional `str | None` field like
        # `analysis_model` is *absent* from the mirror when unset — the
        # semantic assertion is "this is not an ability_analysis", which
        # is equally true whether the key is missing or explicitly None.
        assert profile.get("analysis_model") is None
        assert profile["confidence"] >= DEFAULT_AUTO_ADMIT_THRESHOLD, (
            f"sample 1 confidence dropped to {profile['confidence']}"
        )

    def test_profile_also_written_into_normalized_payload(self, state, session):
        _, storage = state
        ref = _normalized_ref(session)
        payload = _normalized_payload(storage, ref)
        assert payload["profile"]["record_type"] == "job_demand_dataset"
        # contract-freeze §5.0: payload-level record_type follows the detector,
        # not the legacy raw_object.metadata_summary fallback ("generic").
        assert payload["record_type"] == "job_demand_dataset"

    def test_version_stays_processing_for_canonical_high_confidence(self, state, session):
        # High-confidence canonical detections must NOT be pre-parked —
        # they wait for governance_decision (or a later stage) to drive
        # the next transition.
        versions = list(session.scalars(select(models.AssetVersion)))
        assert len(versions) == 1
        assert versions[0].version_status == AssetVersionStatus.PROCESSING

    def test_only_detected_audit_fires(self, state, session):
        detected = _audits(session, AuditEventType.RECORD_PROFILE_DETECTED)
        review = _audits(session, AuditEventType.RECORD_PROFILE_REVIEW_REQUIRED)
        assert len(detected) == 1
        assert detected[0].summary["record_type"] == "job_demand_dataset"
        assert review == []

    def test_evidence_captures_real_headers(self, state, session):
        ref = _normalized_ref(session)
        profile = ref.metadata_summary["profile"]
        matched = profile["evidence"]["matched_headers"]
        for required in ["岗位名称", "城市", "公司名称"]:
            assert required in matched


# ---------------------------------------------------------------------------
# Sample 2 — PGSD ability analysis xlsx (high confidence, canonical)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not SAMPLE_ABILITY.exists(), reason="sample missing")
class TestSample2ProfileDetectE2E:
    @pytest.fixture
    def state(self, session):
        storage = InMemoryObjectStorage()
        accepted = _ingest_and_run(
            session, storage,
            content=SAMPLE_ABILITY.read_bytes(),
            filename=SAMPLE_ABILITY.name,
            mime=XLSX_MIME,
            settings=_settings_with_flags(xlsx=True),
            source_code="b24-sample2",
        )
        return accepted, storage

    def test_job_succeeded(self, state):
        accepted, _ = state
        assert accepted.job.status == JobStatus.SUCCEEDED, (
            f"job failed: {accepted.job.failure_reason}"
        )

    def test_profile_detected_as_pgsd_ability_analysis(self, state, session):
        ref = _normalized_ref(session)
        profile = ref.metadata_summary["profile"]
        assert profile["record_type"] == "occupational_ability_analysis"
        assert profile["domain_profile"] == "ability_analysis.pgsd.v1"
        assert profile["analysis_model"] == "PGSD"
        assert profile["confidence"] >= DEFAULT_AUTO_ADMIT_THRESHOLD

    def test_evidence_captures_all_four_categories_and_prefixes(self, state, session):
        ref = _normalized_ref(session)
        ev = ref.metadata_summary["profile"]["evidence"]
        assert set(ev["matched_categories"]) == {
            "职业能力", "通用能力", "社会能力", "发展能力",
        }
        assert set(ev["matched_code_prefixes"]) == {"P", "G", "S", "D"}

    def test_version_stays_processing(self, state, session):
        versions = list(session.scalars(select(models.AssetVersion)))
        assert versions[0].version_status == AssetVersionStatus.PROCESSING


# ---------------------------------------------------------------------------
# Degraded job-demand xlsx — only 1 required header → candidate
# ---------------------------------------------------------------------------


class TestDegradedJobDemandCandidateE2E:
    def _bytes(self) -> bytes:
        # 1 required (`岗位名称`) + filler — confidence lands well below 0.85.
        return _build_xlsx(
            lambda wb: (
                wb.active.append(["岗位名称", "filler1", "filler2"])
                or wb.active.append(["dev", "x", "y"])
            )
        )

    @pytest.fixture
    def state(self, session):
        storage = InMemoryObjectStorage()
        accepted = _ingest_and_run(
            session, storage,
            content=self._bytes(),
            filename="degraded_jd.xlsx",
            mime=XLSX_MIME,
            settings=_settings_with_flags(xlsx=True),
            source_code="b24-degraded-jd",
        )
        return accepted, storage

    def test_job_succeeded(self, state):
        accepted, _ = state
        assert accepted.job.status == JobStatus.SUCCEEDED

    def test_record_type_downgraded_to_candidate(self, state, session):
        ref = _normalized_ref(session)
        profile = ref.metadata_summary["profile"]
        assert profile["record_type"] == "job_demand_dataset_candidate"
        # domain_profile preserved — only record_type is downgraded
        assert profile["domain_profile"] == "job_demand.v1"
        assert profile["confidence"] < DEFAULT_AUTO_ADMIT_THRESHOLD

    def test_version_parked_in_review_required(self, state, session):
        versions = list(session.scalars(select(models.AssetVersion)))
        assert versions[0].version_status == AssetVersionStatus.REVIEW_REQUIRED

    def test_both_audit_events_fire_with_consistent_payload(self, state, session):
        detected = _audits(session, AuditEventType.RECORD_PROFILE_DETECTED)
        review = _audits(session, AuditEventType.RECORD_PROFILE_REVIEW_REQUIRED)
        assert len(detected) == 1
        assert len(review) == 1
        # Both audits reference the same record_type / detector_version
        assert detected[0].summary["record_type"] == review[0].summary["record_type"]
        assert detected[0].summary["detector_version"] == review[0].summary["detector_version"]

    def test_version_status_changed_audit_emitted_once(self, state, session):
        vsc = [
            a for a in _audits(session, AuditEventType.VERSION_STATUS_CHANGED)
            if a.summary.get("reason") == "profile_detect_candidate_or_low_confidence"
        ]
        assert len(vsc) == 1
        assert vsc[0].summary["previous_status"] == "processing"
        assert vsc[0].summary["current_status"] == "review_required"


# ---------------------------------------------------------------------------
# Degraded PGSD xlsx — only some categories present → candidate
# ---------------------------------------------------------------------------


class TestDegradedPgsdCandidateE2E:
    def _bytes(self) -> bytes:
        # Single category + single code prefix + single per-task sheet —
        # the PGSD detector registers some signal but well below 0.85.
        def build(wb):
            ws = wb.active
            ws.title = "1.数据采集"
            ws.append(["能力分析表"])
            ws.append(["职业能力", "P-1.1.1", "data collection skill"])
        return _build_xlsx(build)

    @pytest.fixture
    def state(self, session):
        storage = InMemoryObjectStorage()
        accepted = _ingest_and_run(
            session, storage,
            content=self._bytes(),
            filename="degraded_pgsd.xlsx",
            mime=XLSX_MIME,
            settings=_settings_with_flags(xlsx=True),
            source_code="b24-degraded-pgsd",
        )
        return accepted, storage

    def test_classified_as_ability_analysis_candidate(self, state, session):
        ref = _normalized_ref(session)
        profile = ref.metadata_summary["profile"]
        assert profile["record_type"] == "occupational_ability_analysis_candidate"
        # PGSD-specific fields still populated even at candidate confidence —
        # so the review UI can render the partial evidence.
        assert profile["domain_profile"] == "ability_analysis.pgsd.v1"
        assert profile["analysis_model"] == "PGSD"
        assert profile["confidence"] < DEFAULT_AUTO_ADMIT_THRESHOLD

    def test_version_parked_in_review_required(self, state, session):
        versions = list(session.scalars(select(models.AssetVersion)))
        assert versions[0].version_status == AssetVersionStatus.REVIEW_REQUIRED


# ---------------------------------------------------------------------------
# Generic xlsx — no specialised signal at all → generic_table_dataset
# ---------------------------------------------------------------------------


class TestGenericTableFallbackE2E:
    def _bytes(self) -> bytes:
        return _build_xlsx(
            lambda wb: (
                wb.active.append(["alpha", "beta", "gamma"])
                or wb.active.append(["1", "2", "3"])
            )
        )

    def test_falls_back_to_generic_and_parks_for_review(self, session):
        storage = InMemoryObjectStorage()
        accepted = _ingest_and_run(
            session, storage,
            content=self._bytes(),
            filename="anonymous.xlsx",
            mime=XLSX_MIME,
            settings=_settings_with_flags(xlsx=True),
            source_code="b24-generic",
        )
        assert accepted.job.status == JobStatus.SUCCEEDED

        ref = _normalized_ref(session)
        profile = ref.metadata_summary["profile"]
        assert profile["record_type"] == "generic_table_dataset"
        assert profile["domain_profile"] == "generic_table.v1"

        versions = list(session.scalars(select(models.AssetVersion)))
        assert versions[0].version_status == AssetVersionStatus.REVIEW_REQUIRED


# ---------------------------------------------------------------------------
# Flag-off — xlsx routes to DOCUMENT and profile_detect is NOT invoked
# ---------------------------------------------------------------------------


class TestFlagOffSkipsProfileDetect:
    def test_xlsx_with_flag_off_does_not_invoke_profile_detect(self, session):
        storage = InMemoryObjectStorage()
        source = _create_source(session, code="b24-flag-off")
        # Don't even need to run the worker — flag-off routing means the
        # gateway writes pipeline_type="document" so the record-branch
        # detector path is never taken.
        accepted = submit_file_bytes(
            session,
            data_source_id=source.id,
            idempotency_key="b24-flag-off-key",
            content=_build_xlsx(
                lambda wb: wb.active.append(["岗位名称", "城市", "公司名称"])
            ),
            filename="x.xlsx",
            content_type=XLSX_MIME,
            storage=storage,
            settings=_settings_with_flags(xlsx=False),
            trace_id="trace-flag-off",
        )
        assert accepted.job.payload["pipeline_type"] == PipelineType.DOCUMENT.value
        # No worker execution → no profile audits possible
        assert _audits(session, AuditEventType.RECORD_PROFILE_DETECTED) == []
        assert _audits(session, AuditEventType.RECORD_PROFILE_REVIEW_REQUIRED) == []


# ---------------------------------------------------------------------------
# csv path — profile_detect runs on csv too (record_type likely generic
# because csv has only one sheet "csv" and our job_demand detector keys
# off recruiting headers, not file format).
# ---------------------------------------------------------------------------


class TestCsvProfileDetectE2E:
    def test_csv_with_recruiting_headers_detects_job_demand(self, session):
        # csv with the full recruiting header set should clear auto-admit.
        storage = InMemoryObjectStorage()
        csv_text = (
            "岗位名称,城市,公司名称,薪资,学历要求,岗位描述\n"
            "平面设计师,上海,ACME,10k-15k,本科,...\n"
            "开发,北京,Foo,20k-30k,硕士,...\n"
        )
        # UTF-8 with BOM — common Excel CSV export shape; the csv parser
        # strips the BOM via its encoding fallback.
        csv_bytes = csv_text.encode("utf-8-sig")
        accepted = _ingest_and_run(
            session, storage,
            content=csv_bytes,
            filename="hires.csv",
            mime=CSV_MIME,
            settings=_settings_with_flags(csv=True),
            source_code="b24-csv-jd",
        )
        assert accepted.job.status == JobStatus.SUCCEEDED, (
            f"job failed: {accepted.job.failure_reason}"
        )

        ref = _normalized_ref(session)
        profile = ref.metadata_summary["profile"]
        assert profile["record_type"] == "job_demand_dataset"
        assert profile["confidence"] >= DEFAULT_AUTO_ADMIT_THRESHOLD

        # Detected audit emitted from the csv path
        detected = _audits(session, AuditEventType.RECORD_PROFILE_DETECTED)
        assert len(detected) == 1
