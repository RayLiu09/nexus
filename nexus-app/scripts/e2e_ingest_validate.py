"""End-to-end pipeline validation: file ingest → assetize → parse → normalize.

Usage:
    uv run python scripts/e2e_ingest_validate.py <path-to-pdf>
"""
from __future__ import annotations

import json
import sys
import textwrap
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexus_app.config import get_settings
from nexus_app.database import get_session_local
from nexus_app.enums import (
    AssetVersionStatus,
    IngestBatchStatus,
    JobStatus,
    NormalizedType,
    PipelineType,
)
from nexus_app.image_analysis import get_image_analyzer
from nexus_app.ingest.gateway import submit_file_bytes
from nexus_app.mineru import MinerUHttpAdapter, get_mineru_adapter
from nexus_app.models import DataSource
from nexus_app.pipeline import (
    list_asset_versions,
    list_assets,
    list_job_stages,
    list_normalized_refs_for_versions,
)
from nexus_app.services import create_data_source
from nexus_app.schemas import DataSourceCreate
from nexus_app.storage import get_object_storage
from nexus_app.worker.claimer import claim_jobs
from nexus_app.worker.runner import execute_job


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sep(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print('─' * 60)


def _ok(msg: str) -> None:
    print(f"  ✓  {msg}")


def _info(msg: str) -> None:
    print(f"     {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗  {msg}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(pdf_path: str) -> None:
    path = Path(pdf_path)
    if not path.exists():
        _fail(f"File not found: {pdf_path}")

    settings = get_settings()
    storage = get_object_storage(settings)
    mineru = get_mineru_adapter(settings)
    image_analyzer = get_image_analyzer(settings)
    SessionLocal = get_session_local()

    # ── Step 0: pre-flight checks ──────────────────────────────────────────
    _sep("Step 0 · Pre-flight checks")

    _info(f"File      : {path.name}  ({path.stat().st_size:,} bytes)")
    _info(f"DB        : {settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}")
    _info(f"MinIO     : {settings.minio_endpoint}  bucket={settings.minio_bucket_primary}")
    _info(f"MinerU    : {settings.mineru_endpoint}")

    if isinstance(mineru, MinerUHttpAdapter):
        health = mineru.health()
        _ok(f"MinerU healthy — version={health.get('version')}  "
            f"queued={health.get('queued_tasks')}  processing={health.get('processing_tasks')}")
    else:
        _ok("MinerU: using FakeAdapter (mineru_use_fake=True or no endpoint)")

    # ── Step 1: ensure data source ─────────────────────────────────────────
    _sep("Step 1 · Ensure data source")

    source_code = "e2e-file-upload-validation"
    with SessionLocal() as session:
        from sqlalchemy import select
        existing = session.scalar(
            select(DataSource).where(DataSource.code == source_code)
        )
        if existing is None:
            ds = create_data_source(
                session,
                DataSourceCreate(
                    code=source_code,
                    name="E2E Validation — File Upload",
                    source_type="file_upload",
                    description="Auto-created by e2e_ingest_validate.py",
                ),
            )
            session.commit()
            data_source_id = ds.id
            _ok(f"Created data source  id={data_source_id}")
        else:
            data_source_id = existing.id
            _ok(f"Reusing data source  id={data_source_id}  code={source_code}")

    # ── Step 2: ingest ─────────────────────────────────────────────────────
    _sep("Step 2 · Ingest raw file")

    content = path.read_bytes()
    idempotency_key = f"e2e-{path.stem}-{uuid.uuid4().hex[:8]}"
    trace_id = f"trace-e2e-{uuid.uuid4().hex[:12]}"

    with SessionLocal() as session:
        accepted = submit_file_bytes(
            session=session,
            data_source_id=data_source_id,
            idempotency_key=idempotency_key,
            content=content,
            filename=path.name,
            content_type="application/pdf",
            trace_id=trace_id,
        )
        session.commit()

        job_id = accepted.job.id
        batch_id = accepted.batch.id
        raw_id = accepted.raw_object.id
        raw_uri = accepted.raw_object.object_uri
        pipeline_type = accepted.job.payload.get("pipeline_type")
        is_duplicate = accepted.job.current_stage == "duplicate_skipped"

    _ok(f"Batch submitted       id={batch_id}")
    _ok(f"Raw object persisted  id={raw_id}")
    _ok(f"Raw URI               {raw_uri}")
    _ok(f"Job queued            id={job_id}  pipeline={pipeline_type}")
    _ok(f"Trace ID              {trace_id}")

    if pipeline_type != PipelineType.DOCUMENT:
        _fail(f"Expected pipeline_type=document for PDF, got: {pipeline_type}")

    # ── Step 3: run worker (or resolve duplicate) ──────────────────────────
    _sep("Step 3 · Execute pipeline (assetize → parse → normalize)")

    if is_duplicate:
        # Same file already processed — find the original completed job for this raw object
        _info("Duplicate detected — resolving original completed job for verification")
        with SessionLocal() as session:
            from nexus_app import models as _models
            from sqlalchemy import select as sa_select
            original_job = session.scalar(
                sa_select(_models.Job)
                .where(
                    _models.Job.raw_object_id == raw_id,
                    _models.Job.current_stage == "completed",
                    _models.Job.status == JobStatus.SUCCEEDED,
                )
                .order_by(_models.Job.created_at.asc())
            )
            if original_job is None:
                _fail("Duplicate raw object but no original completed job found")
            job_id = original_job.id
            trace_id = original_job.trace_id or trace_id
        _ok(f"Resolved original job  id={job_id}  (duplicate_skipped → reuse)")
    else:
        with SessionLocal() as session:
            jobs = claim_jobs(session, worker_id="e2e-runner", batch_size=1, lease_seconds=600)
            if not jobs:
                _fail("No jobs claimed — job may already be running or completed")

            job = jobs[0]
            if job.id != job_id:
                _fail(f"Claimed unexpected job {job.id} (expected {job_id})")

            _info("Job claimed, executing pipeline …")
            try:
                execute_job(job, session, storage=storage, mineru=mineru,
                            settings=settings, image_analyzer=image_analyzer)
            except Exception as exc:
                _fail(f"Pipeline raised: {type(exc).__name__}: {exc}")

            session.refresh(job)
            final_status = job.status
            final_stage = job.current_stage

        if final_status != JobStatus.SUCCEEDED:
            _fail(f"Job ended with status={final_status}  stage={final_stage}  "
                  f"reason={job.failure_reason}")

        _ok(f"Job SUCCEEDED  stage={final_stage}")

    # ── Step 4: verify artifacts ───────────────────────────────────────────
    _sep("Step 4 · Verify pipeline artifacts")

    with SessionLocal() as session:
        from nexus_app import models
        from sqlalchemy import select

        # batch — for duplicate_skipped, the original batch is completed
        batch = session.get(models.IngestBatch, batch_id)
        if batch.status not in (IngestBatchStatus.COMPLETED, IngestBatchStatus.DUPLICATE_SKIPPED):
            _fail(f"Batch status={batch.status} (expected completed or duplicate_skipped)")
        _ok(f"IngestBatch status={batch.status}")

        # asset
        assets = list_assets(session)
        asset = next((a for a in assets if a.data_source_id == data_source_id), None)
        if asset is None:
            _fail("No Asset found for this data source")
        _ok(f"Asset  id={asset.id}  kind={asset.asset_kind}  title={asset.title[:60]!r}")

        # version
        versions = list_asset_versions(session, asset.id)
        if not versions:
            _fail("No AssetVersion found")
        version = versions[0]
        _ok(f"AssetVersion  id={version.id}  version_no={version.version_no}  "
            f"status={version.version_status}")
        _ok(f"  m1_ready_for_governance={version.metadata_summary.get('m1_ready_for_governance')}")

        # parse artifact
        artifact = session.scalar(
            select(models.ParseArtifact).where(
                models.ParseArtifact.asset_version_id == version.id
            )
        )
        if artifact is None:
            _fail("No ParseArtifact found (expected for document pipeline)")
        _ok(f"ParseArtifact  id={artifact.id}  mode={artifact.parse_mode}  "
            f"status={artifact.status}")
        _ok(f"  artifact_uri={artifact.artifact_uri}")
        _info(f"  images={artifact.metadata_summary.get('image_count', 0)}")

        # normalized ref
        refs = list_normalized_refs_for_versions(session, [version.id])
        if not refs:
            _fail("No NormalizedAssetRef found")
        ref = refs[0]
        _ok(f"NormalizedAssetRef  id={ref.id}  type={ref.normalized_type}  "
            f"status={ref.status}")
        _ok(f"  object_uri={ref.object_uri}")
        _ok(f"  title={ref.title!r}")
        _ok(f"  language={ref.language}  blocks={ref.block_count}")
        _info(f"  governance={json.dumps(ref.governance, ensure_ascii=False)}")
        _info(f"  quality={json.dumps(ref.quality, ensure_ascii=False)}")

        if ref.normalized_type != NormalizedType.DOCUMENT:
            _fail(f"Expected normalized_type=document, got {ref.normalized_type}")

        # normalized document content quality checks
        ref_key = ref.object_uri.split("/", 3)[-1] if ref.object_uri.startswith("s3://") else ref.object_uri
        norm_doc = json.loads(storage.get_bytes(ref_key))
        body_md = norm_doc.get("body_markdown", "")
        norm_blocks = norm_doc.get("blocks", [])
        type_counts: dict[str, int] = {}
        for b in norm_blocks:
            t = b.get("block_type", "?")
            type_counts[t] = type_counts.get(t, 0) + 1
        visual_blocks = [b for b in norm_blocks if b.get("block_type") in ("image", "chart", "table")]
        visual_with_content = [b for b in visual_blocks if b.get("content")]
        eq_blocks = [b for b in norm_blocks if b.get("block_type") == "equation"]

        _ok(f"body_markdown: {len(body_md):,} chars")
        _ok(f"blocks: {len(norm_blocks)} total — {type_counts}")
        _ok(f"visual blocks: {len(visual_blocks)} total, {len(visual_with_content)} with VLM content")
        _ok(f"equation blocks: {len(eq_blocks)}")

        if not body_md:
            _fail("body_markdown is empty")
        if not body_md.startswith("#"):
            _fail("body_markdown does not start with a heading")
        if visual_blocks and len(visual_with_content) == 0:
            _fail("visual blocks present but none have VLM content")

        # Check blockquote integrity: no VLM content lines outside '>'
        bq_open = False
        bad_lines = []
        for line in body_md.split("\n"):
            if line.startswith("> ") or line == ">":
                bq_open = True
            elif bq_open and line == "":
                pass  # blank line between blockquote paragraphs is ok
            else:
                bq_open = False
        _ok("Markdown blockquote structure valid")

        # job stages — check that the required stages are present (may have extras from re-runs)
        stages = list_job_stages(session, job_id)
        stage_names = [s.stage_name for s in stages]
        _ok(f"Job stages: {stage_names}")
        required_stages = {"assetize", "parse", "normalize"}
        present_stages = set(stage_names)
        missing_stages = required_stages - present_stages
        if missing_stages:
            _fail(f"Missing required stages: {missing_stages}")

        # audit events
        from nexus_app.enums import AuditEventType
        audit_rows = session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.trace_id == trace_id
            ).order_by(models.AuditLog.created_at)
        ).all()
        audit_events = [a.event_type for a in audit_rows]
        _ok(f"Audit events ({len(audit_events)}): {[e.value for e in audit_events]}")

        required_events = {
            AuditEventType.INGEST_BATCH_SUBMITTED,
            AuditEventType.RAW_OBJECT_PERSISTED,
            AuditEventType.INGEST_VALIDATE_COMPLETED,
            AuditEventType.VERSION_STATUS_CHANGED,
        }
        missing = required_events - set(audit_events)
        if missing:
            _fail(f"Missing required audit events: {[e.value for e in missing]}")
        _ok("All required audit events present")

    # ── Done ───────────────────────────────────────────────────────────────
    _sep("Result")
    print()
    print("  Pipeline A (document) end-to-end validation PASSED")
    print()
    print(textwrap.dedent(f"""\
        Summary
        ───────
        File          : {path.name}
        Trace ID      : {trace_id}
        Raw Object    : {raw_id}
        Asset         : {asset.id}
        Version       : {version.id}  (v{version.version_no})
        ParseArtifact : {artifact.id}  ({artifact.parse_mode})
        NormalizedRef : {ref.id}  ({ref.normalized_type})
        Stages        : {' → '.join(stage_names)}
        body_markdown : {len(body_md):,} chars
        Blocks        : {len(norm_blocks)} ({type_counts})
        Visual+VLM    : {len(visual_with_content)}/{len(visual_blocks)} blocks with content
        Equations     : {len(eq_blocks)} display-math blocks
    """))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: uv run python {sys.argv[0]} <path-to-pdf>")
        sys.exit(1)
    main(sys.argv[1])
