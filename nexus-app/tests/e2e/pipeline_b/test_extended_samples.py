"""B10.2 — flexibility-boundary tests on synthetic extended samples.

The two canonical samples (sample 1 / sample 2) cover the happy paths.
This file exercises the **deliberately-not-happy** cases the acceptance
gate requires per `pipeline_b_implementation_plan.md §B10`:

  (a) Job-demand xlsx with header alias variants AND a missing optional
      field → adapter still extracts; quality_flags log the absence.
  (b) Job-demand xlsx with a non-standard `企业规模` text → writer keeps
      raw value (decision 7 forbids normalization / range CHECK).
  (c) Ability-analysis xlsx that's missing the overview sheet → B7
      cross_sheet rule short-circuits silently (loose mode), other
      rules still pass on the clean per-task sheets.

All samples are built in-process via openpyxl so we don't ship 3 extra
xlsx blobs in the repo. The synthesis follows the same column / sheet
conventions sample 1 / 2 use, just with the targeted variation.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from nexus_app import models, services
from nexus_app.config import Settings
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

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _xlsx_bytes(builder) -> bytes:
    """Run an openpyxl-Workbook-building callable and return its bytes."""
    wb = Workbook()
    builder(wb)
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def _build_job_demand_with_aliases(wb: Workbook) -> None:
    """Sample (a): job_demand using header aliases (`职位` not `岗位名称`)."""
    sheet = wb.active
    assert sheet is not None
    sheet.title = "Sheet1"
    # B1.2 strips '序号' column → put it in col A so the rest of the
    # mapping mirrors the real sample.
    sheet.append([
        "序号", "职位", "工作地点", "公司", "薪资", "学历", "工作经验",
    ])
    sheet.append([1, "数据分析师 (远程)", "北京", "字节跳动", "20k-35k", "本科", "3-5年"])
    sheet.append([2, "BI 工程师", "上海", "美团", "25k-40k", "硕士", "5年以上"])


def _build_job_demand_with_exotic_size(wb: Workbook) -> None:
    """Sample (b): non-standard enterprise_size text (Latin chars + range)."""
    sheet = wb.active
    assert sheet is not None
    sheet.title = "Sheet1"
    sheet.append([
        "序号", "岗位名称", "城市", "公司名称", "企业规模", "薪资",
    ])
    sheet.append([1, "前端开发", "深圳", "腾讯",
                  "Startup (10-50 ppl)", "30k-50k"])
    sheet.append([2, "全栈开发", "杭州", "阿里",
                  "≥ 5000人 / Multi-national", "40k-70k"])


def _build_ability_analysis_no_overview(wb: Workbook) -> None:
    """Sample (c): per-task sheets but no overview matrix.

    B7 rule 6 (cross_sheet_inconsistency) should short-circuit cleanly
    when no overview is present. Other rules still pass against the
    well-formed per-task sheets.
    """
    sheet0 = wb.active
    assert sheet0 is not None
    sheet0.title = "1.数据采集"
    sheet0.append(["类别", "能力编码", "能力内容"])
    sheet0.append(["职业能力", "P-1.1.1", "能用工具采集日志数据"])
    sheet0.append(["职业能力", "P-1.1.2", "能配置 Kafka 采集"])
    sheet0.append(["通用能力", "G-1.1", "团队协作能力强"])
    sheet0.append(["社会能力", "S-1.1", "良好的沟通协作能力"])
    sheet0.append(["发展能力", "D-1.1", "持续学习能力"])

    sheet1 = wb.create_sheet("2.数据清洗")
    sheet1.append(["类别", "能力编码", "能力内容"])
    sheet1.append(["职业能力", "P-2.1.1", "能识别并清洗异常值"])
    sheet1.append(["通用能力", "G-2.1", "细致严谨能力强"])
    sheet1.append(["社会能力", "S-2.1", "良好的协作沟通"])
    sheet1.append(["发展能力", "D-2.1", "持续学习能力强"])


# ---------------------------------------------------------------------------
# Helpers (mirror the acceptance suite)
# ---------------------------------------------------------------------------


def _ingest_xlsx_bytes(
    session, storage: InMemoryObjectStorage, *,
    content: bytes, filename: str, source_code: str,
):
    settings = Settings(pipeline_b_xlsx_enabled=True, pipeline_b_csv_enabled=True)
    source = services.create_data_source(
        session,
        DataSourceCreate(code=source_code, name=source_code,
                         source_type="file_upload"),
    )
    accepted = submit_file_bytes(
        session,
        data_source_id=source.id,
        idempotency_key=f"{source_code}-key",
        content=content, filename=filename, content_type=XLSX_MIME,
        storage=storage, settings=settings,
        trace_id=f"trace-{source_code}",
    )
    session.refresh(accepted.job)
    execute_job(accepted.job, session, storage, FakeMinerUAdapter(), settings)
    session.refresh(accepted.job)
    return accepted


def _ref(session, job: models.Job) -> models.NormalizedAssetRef | None:
    return session.scalar(
        select(models.NormalizedAssetRef)
        .join(models.AssetVersion,
              models.AssetVersion.id == models.NormalizedAssetRef.version_id)
        .where(models.AssetVersion.raw_object_id == job.raw_object_id)
    )


def _audits(session, event: AuditEventType) -> list[models.AuditLog]:
    return list(session.scalars(
        select(models.AuditLog).where(models.AuditLog.event_type == event)
    ))


# ---------------------------------------------------------------------------
# Extended sample (a) — header alias variants
# ---------------------------------------------------------------------------


class TestExtendedSampleHeaderAliases:
    def test_alias_headers_still_extract_records(self, session):
        storage = InMemoryObjectStorage()
        accepted = _ingest_xlsx_bytes(
            session, storage,
            content=_xlsx_bytes(_build_job_demand_with_aliases),
            filename="extended_alias.xlsx",
            source_code="b10-alias",
        )
        assert accepted.job.status == JobStatus.SUCCEEDED

        # B2 still classifies as job_demand even with alias headers.
        events = _audits(session, AuditEventType.RECORD_PROFILE_DETECTED)
        assert events
        assert events[-1].summary["domain_profile"] == "job_demand.v1"

        # B4 writer persisted at least one record despite alias headers.
        records = list(session.scalars(select(models.JobDemandRecord)))
        assert records
        # Adapter mapped `职位` → job_title (alias for 岗位名称).
        titles = {r.job_title for r in records}
        assert any("数据分析师" in t for t in titles)


# ---------------------------------------------------------------------------
# Extended sample (b) — exotic enterprise_size text
# ---------------------------------------------------------------------------


class TestExtendedSampleExoticEnterpriseSize:
    def test_writer_preserves_raw_enterprise_size_text(self, session):
        storage = InMemoryObjectStorage()
        accepted = _ingest_xlsx_bytes(
            session, storage,
            content=_xlsx_bytes(_build_job_demand_with_exotic_size),
            filename="extended_exotic_size.xlsx",
            source_code="b10-size",
        )
        assert accepted.job.status == JobStatus.SUCCEEDED

        records = list(session.scalars(select(models.JobDemandRecord)))
        sizes = {r.enterprise_size for r in records if r.enterprise_size}
        # Decision 7 forbids normalization / range CHECK — raw text MUST
        # round-trip verbatim through the writer.
        assert "Startup (10-50 ppl)" in sizes
        assert "≥ 5000人 / Multi-national" in sizes


# ---------------------------------------------------------------------------
# Extended sample (c) — ability_analysis without overview sheet
# ---------------------------------------------------------------------------


class TestExtendedSampleAbilityAnalysisNoOverview:
    def test_pipeline_succeeds_without_overview(self, session):
        storage = InMemoryObjectStorage()
        accepted = _ingest_xlsx_bytes(
            session, storage,
            content=_xlsx_bytes(_build_ability_analysis_no_overview),
            filename="extended_no_overview.xlsx",
            source_code="b10-noov",
        )
        assert accepted.job.status == JobStatus.SUCCEEDED

    def test_b6_persists_analysis_with_per_task_sheets_only(self, session):
        storage = InMemoryObjectStorage()
        _ingest_xlsx_bytes(
            session, storage,
            content=_xlsx_bytes(_build_ability_analysis_no_overview),
            filename="extended_no_overview.xlsx",
            source_code="b10-noov-b6",
        )
        analysis = session.scalar(select(models.OccupationalAbilityAnalysis))
        assert analysis is not None
        tasks = list(session.scalars(select(models.OccupationalWorkTask)))
        assert len(tasks) == 2  # two per-task sheets

    def test_b7_cross_sheet_rule_short_circuits_loose_mode(self, session):
        storage = InMemoryObjectStorage()
        _ingest_xlsx_bytes(
            session, storage,
            content=_xlsx_bytes(_build_ability_analysis_no_overview),
            filename="extended_no_overview.xlsx",
            source_code="b10-noov-b7",
        )
        # B7 governance ran (audit emitted); cross_sheet rule did NOT fire
        # because overview_work_content_codes was None.
        gov_events = _audits(session, AuditEventType.ABILITY_ANALYSIS_GOVERNED)
        assert gov_events
        last = gov_events[-1].summary
        tokens = last.get("rule_tokens_fired") or []
        assert "ability_cross_sheet_inconsistency" not in tokens
        # And the version stays PROCESSING — no blocking findings on a
        # well-formed (if overview-less) sample.
        # (review_required would only fire on blocking rules.)
        assert last.get("review_required") is False
