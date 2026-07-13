"""Real-sample end-to-end ingestion validation for v1.3 E2E plan (Phase-1).

Scans a samples directory (default ``docs/samples/``), routes every
supported file through Pipeline A (PDF/DOCX/HTML → document) or Pipeline
B (xlsx → record), runs the worker inline, then verifies the produced
``asset`` / ``asset_version`` / ``parse_artifact`` / ``normalized_asset_ref``
/ ``governance_result.tags`` (v2 分类型结构) / ``tag_asset_index`` /
``knowledge_outline_node`` / ``chunk`` matches the v1.3 contract.

Complements ``scripts/e2e_ingest_validate.py`` (single-file smoke) by:

* handling xlsx / docx / html in addition to pdf
* using the real LiteLLM path (no ``_run_pipeline_without_live_llm``
  stub — Phase-1 acceptance requires the tagging v2 profile actually runs)
* emitting a machine-readable JSON report suitable for CI artifact
* accumulating per-file outcomes so one bad sample does not abort the
  batch (batch-level pass rate + per-file status matrix)

Usage::

    uv run python scripts/e2e_ingest_real_samples.py \
        --samples-dir docs/samples \
        --report tmp/e2e_ingest_report.json

    # smoke: only first 3 files, dry-run planning only
    uv run python scripts/e2e_ingest_real_samples.py --limit 3 --dry-run

    # single-file focus
    uv run python scripts/e2e_ingest_real_samples.py \
        --include-pattern '*直播电商*'

Exit codes:

* ``0`` — every processed sample passed
* ``1`` — one or more samples failed but the harness itself is healthy
* ``2`` — harness precondition failure (missing dir, DB, LiteLLM, flag)
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.config import Settings, get_settings
from nexus_app.database import get_session_local
from nexus_app.enums import (
    AssetVersionStatus,
    AuditEventType,
    IngestBatchStatus,
    JobStatus,
    NormalizedType,
    PipelineType,
    TagAssetIndexSource,
    TagAssetIndexTargetType,
)
from nexus_app.image_analysis import get_image_analyzer
from nexus_app.ingest.gateway import (
    CSV_MIME_TYPES,
    XLSX_MIME_TYPES,
    submit_file_bytes,
)
from nexus_app.mineru import get_mineru_adapter
from nexus_app.pipeline import (
    list_asset_versions,
    list_assets,
    list_job_stages,
    list_normalized_refs_for_versions,
)
from nexus_app.schemas import DataSourceCreate
from nexus_app.services import create_data_source
from nexus_app.storage import get_object_storage
from nexus_app.worker.claimer import claim_jobs
from nexus_app.worker.runner import execute_job


# ---------------------------------------------------------------------------
# MIME map — kept local so an unfamiliar extension surfaces here rather
# than as an obscure MinerU / xlsx-parser error deep in the pipeline.
# ---------------------------------------------------------------------------

_MIME_BY_EXT: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    ".doc": "application/msword",
    ".html": "text/html",
    ".htm": "text/html",
    ".xlsx": next(iter(XLSX_MIME_TYPES)),
    ".xls": "application/vnd.ms-excel",
    ".csv": next(iter(CSV_MIME_TYPES)),
}

# Files we deliberately skip — prototype HTML mockups etc.
_SKIP_STEMS_LOWER: frozenset[str] = frozenset({"prototype-v3.1", "prototype-v3.2"})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SampleOutcome:
    filename: str
    size_bytes: int
    mime_type: str
    expected_pipeline: str
    status: str = "pending"  # pending | passed | failed | skipped
    failure: str | None = None
    checks: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    job_id: str | None = None
    asset_id: str | None = None
    version_id: str | None = None
    duration_ms: float | None = None


@dataclass
class RunReport:
    started_at: float
    finished_at: float | None = None
    settings: dict[str, Any] = field(default_factory=dict)
    samples: list[SampleOutcome] = field(default_factory=list)
    skipped_files: list[dict[str, str]] = field(default_factory=list)
    aggregates: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Precondition checks — mirror scripts/e2e_readiness_check.py but only
# the subset Phase-1 depends on, so this script stays runnable in envs
# where the full readiness check is not desirable.
# ---------------------------------------------------------------------------


def _preflight(settings: Settings, session: Session) -> list[str]:
    issues: list[str] = []
    try:
        session.scalar(select(func.count()).select_from(models.DimTagAlias))
    except Exception as exc:  # noqa: BLE001
        issues.append(f"alembic head missing (dim_tag_alias): {exc}")

    if not settings.pipeline_b_xlsx_enabled:
        issues.append(
            "settings.pipeline_b_xlsx_enabled=False — xlsx files would "
            "route to Pipeline A. Set PIPELINE_B_XLSX_ENABLED=true."
        )

    active_prompts = {
        row[0]
        for row in session.execute(
            select(models.GovernancePromptTemplate.task_type).where(
                models.GovernancePromptTemplate.status == "active"
            )
        )
    }
    required = {"classification", "level_assessment", "tagging", "knowledge_type_inference"}
    missing = required - active_prompts
    if missing:
        issues.append(f"governance prompts missing (active): {sorted(missing)}")

    if not settings.litellm_endpoint or not settings.litellm_api_key:
        issues.append("LITELLM_ENDPOINT / LITELLM_API_KEY not configured")

    return issues


# ---------------------------------------------------------------------------
# Sample discovery
# ---------------------------------------------------------------------------


def _discover(
    samples_dir: Path,
    include_pattern: str | None,
    exclude_pattern: str | None,
    limit: int | None,
) -> tuple[list[Path], list[tuple[str, str]]]:
    """Return (accepted_files, [(skipped_filename, reason), ...])."""
    if not samples_dir.exists() or not samples_dir.is_dir():
        raise SystemExit(f"samples dir not found: {samples_dir}")

    files: list[Path] = []
    skipped: list[tuple[str, str]] = []
    for child in sorted(samples_dir.iterdir()):
        if not child.is_file():
            continue
        if child.stem.lower() in _SKIP_STEMS_LOWER:
            skipped.append((child.name, "prototype (explicit skip)"))
            continue
        ext = child.suffix.lower()
        if ext not in _MIME_BY_EXT:
            reason = "no extension (likely garbled filename)" if not ext else f"unsupported extension: {ext}"
            skipped.append((child.name, reason))
            continue
        if include_pattern and not fnmatch.fnmatch(child.name, include_pattern):
            skipped.append((child.name, "include-pattern excluded"))
            continue
        if exclude_pattern and fnmatch.fnmatch(child.name, exclude_pattern):
            skipped.append((child.name, "exclude-pattern matched"))
            continue
        files.append(child)
    if limit is not None:
        files = files[:limit]
    return files, skipped


def _expected_pipeline(mime: str, settings: Settings) -> str:
    normalized = mime.lower()
    if normalized in XLSX_MIME_TYPES and settings.pipeline_b_xlsx_enabled:
        return PipelineType.RECORD.value
    if normalized in CSV_MIME_TYPES and settings.pipeline_b_csv_enabled:
        return PipelineType.RECORD.value
    return PipelineType.DOCUMENT.value


# ---------------------------------------------------------------------------
# Per-sample execution
# ---------------------------------------------------------------------------


_DATA_SOURCE_CODE = "e2e-real-samples"


def _ensure_data_source(session: Session) -> str:
    existing = session.scalar(
        select(models.DataSource).where(models.DataSource.code == _DATA_SOURCE_CODE)
    )
    if existing is not None:
        return existing.id
    ds = create_data_source(
        session,
        DataSourceCreate(
            code=_DATA_SOURCE_CODE,
            name="E2E — Real Samples (v1.3 Phase-1)",
            source_type="file_upload",
            description="Auto-created by scripts/e2e_ingest_real_samples.py",
        ),
    )
    session.commit()
    return ds.id


def _process_sample(
    path: Path,
    mime: str,
    data_source_id: str,
    settings: Settings,
    storage,
    mineru,
    image_analyzer,
    session_factory,
    dry_run: bool,
) -> SampleOutcome:
    outcome = SampleOutcome(
        filename=path.name,
        size_bytes=path.stat().st_size,
        mime_type=mime,
        expected_pipeline=_expected_pipeline(mime, settings),
    )
    if dry_run:
        outcome.status = "skipped"
        outcome.failure = "dry-run"
        return outcome

    trace_id = f"trace-e2e-samples-{uuid.uuid4().hex[:12]}"
    idem = f"e2e-samples-{path.stem}-{uuid.uuid4().hex[:8]}"
    outcome.trace_id = trace_id

    started = time.monotonic()
    content = path.read_bytes()

    # --- Submit --------------------------------------------------------
    with session_factory() as session:
        accepted = submit_file_bytes(
            session=session,
            data_source_id=data_source_id,
            idempotency_key=idem,
            content=content,
            filename=path.name,
            content_type=mime,
            trace_id=trace_id,
        )
        session.commit()
        job_id = accepted.job.id
        raw_id = accepted.raw_object.id
        actual_pipeline = accepted.job.payload.get("pipeline_type")
        is_duplicate = accepted.job.current_stage == "duplicate_skipped"

    outcome.job_id = job_id
    outcome.checks["pipeline_type"] = {
        "expected": outcome.expected_pipeline,
        "actual": actual_pipeline,
    }
    if actual_pipeline != outcome.expected_pipeline and not is_duplicate:
        outcome.status = "failed"
        outcome.failure = (
            f"pipeline mismatch: expected {outcome.expected_pipeline}, got {actual_pipeline}"
        )
        outcome.duration_ms = (time.monotonic() - started) * 1000
        return outcome

    # --- Execute -------------------------------------------------------
    if is_duplicate:
        with session_factory() as session:
            original = session.scalar(
                select(models.Job).where(
                    models.Job.raw_object_id == raw_id,
                    models.Job.current_stage == "completed",
                    models.Job.status == JobStatus.SUCCEEDED,
                ).order_by(models.Job.created_at.asc())
            )
            if original is None:
                outcome.status = "failed"
                outcome.failure = "duplicate raw object but no original completed job"
                outcome.duration_ms = (time.monotonic() - started) * 1000
                return outcome
            job_id = original.id
            outcome.job_id = job_id
    else:
        with session_factory() as session:
            claimed = claim_jobs(
                session, worker_id="e2e-real-samples", batch_size=1, lease_seconds=1800
            )
            if not claimed or claimed[0].id != job_id:
                outcome.status = "failed"
                outcome.failure = "job not claimable or wrong id"
                outcome.duration_ms = (time.monotonic() - started) * 1000
                return outcome
            job = claimed[0]
            try:
                execute_job(
                    job, session,
                    storage=storage, mineru=mineru,
                    settings=settings, image_analyzer=image_analyzer,
                )
            except Exception as exc:  # noqa: BLE001
                outcome.status = "failed"
                outcome.failure = f"pipeline raised: {type(exc).__name__}: {exc}"
                outcome.duration_ms = (time.monotonic() - started) * 1000
                return outcome

            session.refresh(job)
            if job.status != JobStatus.SUCCEEDED:
                outcome.status = "failed"
                outcome.failure = (
                    f"job ended with status={job.status.value} stage={job.current_stage} "
                    f"reason={job.failure_reason}"
                )
                outcome.duration_ms = (time.monotonic() - started) * 1000
                return outcome

    # --- Verify --------------------------------------------------------
    with session_factory() as session:
        checks_ok, checks_detail, ids = _verify_artifacts(
            session,
            data_source_id=data_source_id,
            trace_id=trace_id,
            raw_object_id=raw_id,
            expected_pipeline=outcome.expected_pipeline,
        )
        outcome.checks.update(checks_detail)
        outcome.asset_id = ids.get("asset_id")
        outcome.version_id = ids.get("version_id")

    outcome.status = "passed" if checks_ok else "failed"
    if not checks_ok:
        outcome.failure = checks_detail.get("_first_failure", "verification failed")
    outcome.duration_ms = (time.monotonic() - started) * 1000
    return outcome


# ---------------------------------------------------------------------------
# Verification — each check contributes to outcome.checks; the roll-up
# returns (ok, details, ids).
# ---------------------------------------------------------------------------


def _verify_artifacts(
    session: Session,
    *,
    data_source_id: str,
    trace_id: str,
    raw_object_id: str,
    expected_pipeline: str,
) -> tuple[bool, dict[str, Any], dict[str, str]]:
    details: dict[str, Any] = {}
    ids: dict[str, str] = {}
    failures: list[str] = []

    # asset + version
    asset = session.scalar(
        select(models.Asset).where(models.Asset.data_source_id == data_source_id)
        .order_by(models.Asset.created_at.desc())
    )
    if asset is None:
        failures.append("no asset for data source")
        details["_first_failure"] = failures[0]
        return False, details, ids
    ids["asset_id"] = asset.id

    versions = list_asset_versions(session, asset.id)
    if not versions:
        failures.append("no asset_version")
        details["_first_failure"] = failures[0]
        return False, details, ids
    version = versions[0]
    ids["version_id"] = version.id
    details["version_status"] = version.version_status.value

    # normalized ref
    refs = list_normalized_refs_for_versions(session, [version.id])
    if not refs:
        failures.append("no normalized_asset_ref")
    else:
        ref = refs[0]
        details["normalized_ref"] = {
            "id": ref.id,
            "type": ref.normalized_type.value if hasattr(ref.normalized_type, "value") else str(ref.normalized_type),
            "status": ref.status.value if hasattr(ref.status, "value") else str(ref.status),
            "language": ref.language,
            "block_count": ref.block_count,
        }
        expected_type = (
            NormalizedType.DOCUMENT
            if expected_pipeline == PipelineType.DOCUMENT.value
            else NormalizedType.RECORD
        )
        if ref.normalized_type != expected_type:
            failures.append(
                f"normalized_type mismatch: expected {expected_type.value}, "
                f"got {ref.normalized_type.value if hasattr(ref.normalized_type, 'value') else ref.normalized_type}"
            )

    # governance_result.tags v2 shape (dict with 7 buckets)
    gov = session.scalar(
        select(models.GovernanceResult).where(
            models.GovernanceResult.asset_version_id == version.id
        ).order_by(models.GovernanceResult.created_at.desc())
    )
    if gov is None:
        failures.append("no governance_result")
    else:
        tags = gov.tags or {}
        bucket_shape_ok = isinstance(tags, dict) and any(
            k in tags for k in (
                "regions", "industries", "occupations",
                "majors", "abilities", "topics", "time_ranges",
            )
        )
        details["governance_tags"] = {
            "schema_version": gov.rules_schema_version,
            "bucket_shape_ok": bucket_shape_ok,
            "bucket_sizes": {k: (len(v) if isinstance(v, list) else 0) for k, v in tags.items()}
            if isinstance(tags, dict) else None,
        }
        if not bucket_shape_ok:
            failures.append("governance_result.tags is not v2 分类型 shape")

    # tag_asset_index — governance_tag rows on the normalized ref
    if refs:
        ref_id = refs[0].id
        tag_matrix_rows = session.execute(
            select(
                models.TagAssetIndex.source,
                func.count().label("n"),
                func.count(models.TagAssetIndex.tag_embedding).label("with_embed"),
            ).where(
                models.TagAssetIndex.target_type == TagAssetIndexTargetType.NORMALIZED_ASSET_REF,
                models.TagAssetIndex.target_id == ref_id,
            ).group_by(models.TagAssetIndex.source)
        ).all()
        matrix = {}
        for row in tag_matrix_rows:
            src = row.source.value if hasattr(row.source, "value") else str(row.source)
            matrix[src] = {"count": int(row.n), "with_embed": int(row.with_embed or 0)}
        details["tag_asset_index_on_ref"] = matrix
        if TagAssetIndexSource.GOVERNANCE_TAG.value not in matrix:
            failures.append("no governance_tag rows in tag_asset_index for this ref")

    # Pipeline A specific: parse_artifact + outline / chunk
    if expected_pipeline == PipelineType.DOCUMENT.value:
        artifact = session.scalar(
            select(models.ParseArtifact).where(
                models.ParseArtifact.asset_version_id == version.id
            )
        )
        if artifact is None:
            failures.append("no parse_artifact for document pipeline")
        else:
            details["parse_artifact"] = {
                "mode": artifact.parse_mode,
                "status": artifact.status.value if hasattr(artifact.status, "value") else str(artifact.status),
                "image_count": (artifact.metadata_summary or {}).get("image_count", 0),
            }

        if refs:
            outline_count = session.scalar(
                select(func.count()).select_from(models.KnowledgeOutlineNode).where(
                    models.KnowledgeOutlineNode.normalized_ref_id == refs[0].id
                )
            ) or 0
            chunk_count = session.scalar(
                select(func.count()).select_from(models.KnowledgeChunk).where(
                    models.KnowledgeChunk.normalized_ref_id == refs[0].id
                )
            ) or 0
            details["knowledge_counts"] = {
                "outline_nodes": int(outline_count),
                "chunks": int(chunk_count),
            }

    # Pipeline B specific: field_projection rows on child records
    if expected_pipeline == PipelineType.RECORD.value:
        fp_count = session.scalar(
            select(func.count()).select_from(models.TagAssetIndex).where(
                models.TagAssetIndex.asset_version_id == version.id,
                models.TagAssetIndex.source == TagAssetIndexSource.FIELD_PROJECTION,
            )
        ) or 0
        details["tag_asset_index_field_projection"] = int(fp_count)
        if fp_count == 0:
            failures.append("no field_projection rows for record pipeline")

    # audit events — required set from CLAUDE.md
    audit_rows = session.scalars(
        select(models.AuditLog.event_type).where(
            models.AuditLog.trace_id == trace_id
        )
    ).all()
    audit_events = {a.value if hasattr(a, "value") else str(a) for a in audit_rows}
    required_events = {
        AuditEventType.INGEST_BATCH_SUBMITTED.value,
        AuditEventType.RAW_OBJECT_PERSISTED.value,
        AuditEventType.INGEST_VALIDATE_COMPLETED.value,
        AuditEventType.VERSION_STATUS_CHANGED.value,
    }
    missing_events = required_events - audit_events
    details["audit_events"] = sorted(audit_events)
    if missing_events:
        failures.append(f"missing audit events: {sorted(missing_events)}")

    if failures:
        details["_first_failure"] = failures[0]
        details["_all_failures"] = failures
    return not failures, details, ids


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _summarize(report: RunReport) -> dict[str, Any]:
    total = len(report.samples)
    passed = sum(1 for s in report.samples if s.status == "passed")
    failed = sum(1 for s in report.samples if s.status == "failed")
    skipped = sum(1 for s in report.samples if s.status == "skipped")
    by_pipeline: dict[str, dict[str, int]] = {}
    for s in report.samples:
        bucket = by_pipeline.setdefault(
            s.expected_pipeline, {"total": 0, "passed": 0, "failed": 0}
        )
        bucket["total"] += 1
        if s.status == "passed":
            bucket["passed"] += 1
        elif s.status == "failed":
            bucket["failed"] += 1
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "by_pipeline": by_pipeline,
    }


def _print_human(report: RunReport) -> None:
    print()
    print("=" * 72)
    print(f"  v1.3 E2E — Real Samples ({len(report.samples)} files)")
    print("=" * 72)
    for s in report.samples:
        marker = {
            "passed": "PASS",
            "failed": "FAIL",
            "skipped": "SKIP",
            "pending": "----",
        }.get(s.status, "??")
        line = f"  [{marker}] {s.filename}"
        if s.duration_ms is not None:
            line += f"  ({s.duration_ms:.0f} ms)"
        print(line)
        if s.failure:
            print(f"          reason: {s.failure}")
    print()
    print("Aggregates:", json.dumps(report.aggregates, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--samples-dir", default="docs/samples", help="samples directory (default: docs/samples)")
    parser.add_argument("--report", default=None, help="path to write JSON report")
    parser.add_argument("--limit", type=int, default=None, help="only first N files")
    parser.add_argument("--include-pattern", default=None, help="fnmatch include on filename")
    parser.add_argument("--exclude-pattern", default=None, help="fnmatch exclude on filename")
    parser.add_argument("--dry-run", action="store_true", help="plan only, no submit")
    parser.add_argument("--json", action="store_true", help="stdout as JSON")
    args = parser.parse_args()

    settings = get_settings()
    session_factory = get_session_local()

    with session_factory() as session:
        preflight_issues = _preflight(settings, session)
    if preflight_issues:
        for issue in preflight_issues:
            print(f"  BLOCK  {issue}", file=sys.stderr)
        return 2

    samples_dir = Path(args.samples_dir)
    if not samples_dir.is_absolute():
        cwd_candidate = (Path.cwd() / samples_dir).resolve()
        repo_candidate = (_REPO_ROOT.parent / samples_dir).resolve()
        samples_dir = cwd_candidate if cwd_candidate.exists() else repo_candidate
    files, skipped = _discover(samples_dir, args.include_pattern, args.exclude_pattern, args.limit)
    if skipped and not args.json:
        print("Skipped files:", file=sys.stderr)
        for name, reason in skipped:
            print(f"  - {name}  [{reason}]", file=sys.stderr)
    if not files:
        print(f"  no supported samples found under {samples_dir}", file=sys.stderr)
        return 2

    report = RunReport(
        started_at=time.time(),
        skipped_files=[{"filename": n, "reason": r} for n, r in skipped],
        settings={
            "database": f"{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}",
            "minio_bucket": settings.minio_bucket_primary,
            "mineru_endpoint": settings.mineru_endpoint,
            "pipeline_b_xlsx_enabled": settings.pipeline_b_xlsx_enabled,
            "pipeline_b_csv_enabled": settings.pipeline_b_csv_enabled,
            "litellm_endpoint": settings.litellm_endpoint,
            "samples_dir": str(samples_dir),
        },
    )

    if args.dry_run:
        for path in files:
            mime = _MIME_BY_EXT[path.suffix.lower()]
            outcome = SampleOutcome(
                filename=path.name,
                size_bytes=path.stat().st_size,
                mime_type=mime,
                expected_pipeline=_expected_pipeline(mime, settings),
                status="skipped",
                failure="dry-run",
            )
            report.samples.append(outcome)
        report.finished_at = time.time()
        report.aggregates = _summarize(report)
        if args.json:
            print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
        else:
            _print_human(report)
        return 0

    storage = get_object_storage(settings)
    mineru = get_mineru_adapter(settings)
    image_analyzer = get_image_analyzer(settings)

    with session_factory() as session:
        data_source_id = _ensure_data_source(session)

    for path in files:
        mime = _MIME_BY_EXT[path.suffix.lower()]
        try:
            outcome = _process_sample(
                path=path,
                mime=mime,
                data_source_id=data_source_id,
                settings=settings,
                storage=storage,
                mineru=mineru,
                image_analyzer=image_analyzer,
                session_factory=session_factory,
                dry_run=False,
            )
        except Exception as exc:  # noqa: BLE001
            outcome = SampleOutcome(
                filename=path.name,
                size_bytes=path.stat().st_size,
                mime_type=mime,
                expected_pipeline=_expected_pipeline(mime, settings),
                status="failed",
                failure=f"harness exception: {type(exc).__name__}: {exc}",
            )
        report.samples.append(outcome)

    report.finished_at = time.time()
    report.aggregates = _summarize(report)

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if args.json:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    else:
        _print_human(report)

    return 0 if report.aggregates.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
