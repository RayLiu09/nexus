from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.config import Settings, get_settings
from nexus_app.enums import (
    AuditEventType,
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    IngestBatchStatus,
    JobStatus,
    JobType,
    NormalizedAssetRefStatus,
    NormalizedType,
    ParseArtifactStatus,
    RawObjectStatus,
)
from nexus_app.mineru import FakeMinerUAdapter, MinerUAdapter, get_mineru_adapter
from nexus_app.schemas import CrawlerPackageSubmit, IngestFileSubmit
from nexus_app.storage import ObjectStorage, checksum_value, get_object_storage, sha256_hex


@dataclass(frozen=True)
class IngestToAssetResult:
    batch: models.IngestBatch
    raw_object: models.RawObject
    job: models.Job
    asset: models.DocumentAsset | None
    version: models.DocumentVersion | None
    parse_artifact: models.ParseArtifact | None
    normalized_ref: models.NormalizedAssetRef | None


class PipelineError(RuntimeError):
    pass


def _safe_part(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in value)
    return safe.strip(".-")[:120] or "object"


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _object_key(
    partition: str,
    *parts: str,
    extension: str,
    now: datetime | None = None,
) -> str:
    current = now or models.utcnow()
    dated = [f"{current.year:04d}", f"{current.month:02d}", f"{current.day:02d}"]
    safe_parts = [_safe_part(part) for part in parts if part]
    prefix = "/".join([partition.strip("/"), *safe_parts, *dated])
    return f"{prefix}/{_safe_part(parts[-1])}.{extension}"


def _raw_key(
    settings: Settings,
    source_type: DataSourceType,
    source_id: str,
    idempotency_key: str,
    checksum: str,
    filename: str,
) -> str:
    current = models.utcnow()
    return "/".join(
        [
            settings.minio_bucket_partition_raw.strip("/"),
            source_type.value,
            _safe_part(source_id),
            f"{current.year:04d}",
            f"{current.month:02d}",
            f"{current.day:02d}",
            _safe_part(idempotency_key),
            _safe_part(checksum.replace("sha256:", "")[:12]),
            _safe_part(filename),
        ]
    )


def _artifact_key(settings: Settings, version_id: str, artifact_id: str) -> str:
    return "/".join(
        [
            settings.minio_bucket_partition_parsed.strip("/"),
            _safe_part(version_id),
            _safe_part(artifact_id),
            "mineru-result.json",
        ]
    )


def _normalized_key(
    settings: Settings,
    normalized_type: NormalizedType,
    version_id: str,
    ref_id: str,
    checksum: str,
) -> str:
    return "/".join(
        [
            settings.minio_bucket_partition_normalized.strip("/"),
            normalized_type.value,
            _safe_part(version_id),
            _safe_part(ref_id),
            "schema-v1",
            f"{checksum.replace('sha256:', '')[:12]}.json",
        ]
    )


def _find_or_create_batch(
    session: Session,
    data_source_id: str,
    idempotency_key: str,
    source_type: DataSourceType,
    submitted_by_user_id: str | None,
    summary: dict[str, Any],
) -> tuple[models.IngestBatch, bool]:
    existing = session.scalar(
        select(models.IngestBatch).where(
            models.IngestBatch.data_source_id == data_source_id,
            models.IngestBatch.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing, False

    batch = models.IngestBatch(
        data_source_id=data_source_id,
        idempotency_key=idempotency_key,
        source_type=source_type,
        status=IngestBatchStatus.SUBMITTED,
        submitted_by_user_id=submitted_by_user_id,
        summary=summary,
    )
    session.add(batch)
    session.flush()
    return batch, True


def _audit(
    session: Session,
    event_type: AuditEventType,
    target_type: str,
    target_id: str,
    trace_id: str | None,
    summary: dict[str, Any],
    actor_type: str | None = None,
    actor_id: str | None = None,
) -> models.AuditLog:
    audit = models.AuditLog(
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        trace_id=trace_id,
        summary=summary,
    )
    session.add(audit)
    session.flush()
    return audit


def _fail_pipeline(
    session: Session,
    job: models.Job,
    batch: models.IngestBatch,
    raw_object: models.RawObject,
    stage_name: str,
    exc: Exception,
    trace_id: str | None,
) -> None:
    reason = f"{type(exc).__name__}: {exc}"
    job.status = JobStatus.FAILED
    job.current_stage = stage_name
    job.failure_reason = reason[:2000]
    batch.status = IngestBatchStatus.FAILED
    raw_object.status = RawObjectStatus.FAILED
    versions = list(
        session.scalars(
            select(models.DocumentVersion).where(
                models.DocumentVersion.raw_object_id == raw_object.id
            )
        ).all()
    )
    for version in versions:
        previous_status = version.version_status
        version.version_status = AssetVersionStatus.FAILED
        version.failure_reason = reason[:2000]
        if version.asset is not None:
            version.asset.status = AssetVersionStatus.FAILED
        _audit(
            session,
            AuditEventType.VERSION_STATUS_CHANGED,
            "document_version",
            version.id,
            trace_id,
            {
                "from_status": previous_status.value,
                "to_status": AssetVersionStatus.FAILED.value,
                "reason": "pipeline_failed",
            },
        )
    _add_stage(session, job, stage_name, JobStatus.FAILED, failure_reason=reason[:2000])
    _audit(
        session,
        AuditEventType.PIPELINE_FAILED,
        "job",
        job.id,
        trace_id,
        {
            "stage": stage_name,
            "batch_id": batch.id,
            "raw_object_id": raw_object.id,
            "error_type": type(exc).__name__,
        },
    )


def _create_job(
    session: Session,
    batch: models.IngestBatch,
    raw_object: models.RawObject,
    trace_id: str | None,
) -> models.Job:
    job = models.Job(
        job_type=JobType.INGEST_PROCESS,
        status=JobStatus.QUEUED,
        ingest_batch_id=batch.id,
        raw_object_id=raw_object.id,
        current_stage="queued",
        trace_id=trace_id,
        metadata_summary={"pipeline": "m1_ingest_to_asset"},
    )
    session.add(job)
    session.flush()
    return job


def _add_stage(
    session: Session,
    job: models.Job,
    stage_name: str,
    status: JobStatus,
    detail: dict[str, Any] | None = None,
    failure_reason: str | None = None,
) -> models.JobStage:
    now = models.utcnow()
    stage = models.JobStage(
        job_id=job.id,
        stage_name=stage_name,
        status=status,
        started_at=now,
        finished_at=now if status in {JobStatus.SUCCEEDED, JobStatus.FAILED} else None,
        failure_reason=failure_reason,
        detail=detail or {},
    )
    job.current_stage = stage_name
    session.add(stage)
    session.flush()
    return stage


def _asset_kind_for(raw_object: models.RawObject) -> AssetKind:
    if raw_object.source_type in {
        DataSourceType.CRAWLER,
        DataSourceType.WEBHOOK,
        DataSourceType.DATABASE,
    }:
        return AssetKind.RECORD
    if raw_object.mime_type and "json" in raw_object.mime_type:
        return AssetKind.RECORD
    return AssetKind.DOCUMENT


def _title_from(raw_object: models.RawObject, payload: dict[str, Any] | None = None) -> str:
    if payload:
        for key in ("title", "name", "source_title"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:256]
    filename = raw_object.metadata_summary.get("filename")
    if isinstance(filename, str) and filename:
        return filename[:256]
    return raw_object.id


def _create_asset_and_version(
    session: Session,
    raw_object: models.RawObject,
    payload: dict[str, Any] | None,
) -> tuple[models.DocumentAsset, models.DocumentVersion]:
    kind = _asset_kind_for(raw_object)
    source_key = raw_object.source_uri or raw_object.object_uri
    asset = models.DocumentAsset(
        data_source_id=raw_object.data_source_id,
        source_object_key=source_key,
        title=_title_from(raw_object, payload),
        asset_kind=kind,
        status=AssetVersionStatus.PROCESSING,
        org_scope=[],
        metadata_summary={"source_type": raw_object.source_type.value},
    )
    session.add(asset)
    session.flush()
    version = models.DocumentVersion(
        asset_id=asset.id,
        raw_object_id=raw_object.id,
        version_no=1,
        version_status=AssetVersionStatus.PROCESSING,
        source_checksum=raw_object.checksum,
        metadata_summary={"m1": True},
    )
    session.add(version)
    session.flush()
    return asset, version


def _normalize_record(raw_object: models.RawObject, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "normalized-record-v1",
        "source_type": raw_object.source_type.value,
        "record_key": raw_object.source_uri or raw_object.id,
        "title": _title_from(raw_object, payload),
        "record_body": payload,
        "lineage": {"raw_object_id": raw_object.id, "object_uri": raw_object.object_uri},
    }


def _normalize_document(
    raw_object: models.RawObject,
    artifact: models.ParseArtifact,
    parse_payload: dict[str, Any],
) -> dict[str, Any]:
    blocks = parse_payload.get("blocks")
    if not isinstance(blocks, list):
        text = parse_payload.get("markdown") or parse_payload.get("content") or ""
        blocks = [{"block_id": "block-001", "type": "paragraph", "text": str(text)[:4000]}]
    return {
        "schema_version": "normalized-document-v1",
        "title": _title_from(raw_object, parse_payload),
        "source_type": raw_object.source_type.value,
        "blocks": blocks,
        "lineage": {
            "raw_object_id": raw_object.id,
            "raw_object_uri": raw_object.object_uri,
            "parse_artifact_id": artifact.id,
            "parse_artifact_uri": artifact.artifact_uri,
        },
    }


def _create_normalized_ref(
    session: Session,
    storage: ObjectStorage,
    settings: Settings,
    version: models.DocumentVersion,
    normalized_type: NormalizedType,
    normalized_payload: dict[str, Any],
) -> models.NormalizedAssetRef:
    content = _json_bytes(normalized_payload)
    checksum = checksum_value(content)
    ref = models.NormalizedAssetRef(
        version_id=version.id,
        normalized_type=normalized_type,
        object_uri="pending",
        schema_version="schema-v1",
        checksum=checksum,
        status=NormalizedAssetRefStatus.GENERATED,
        block_count=len(normalized_payload.get("blocks", [])),
        record_count=1 if normalized_type == NormalizedType.RECORD else 0,
        metadata_summary={"title": normalized_payload.get("title")},
    )
    session.add(ref)
    session.flush()
    stored = storage.put_bytes(
        _normalized_key(settings, normalized_type, version.id, ref.id, checksum),
        content,
        "application/json",
        {"nexus-version-id": version.id, "nexus-ref-id": ref.id},
    )
    ref.object_uri = stored.object_uri
    session.flush()
    return ref


def _process_raw_object(
    session: Session,
    storage: ObjectStorage,
    settings: Settings,
    raw_object: models.RawObject,
    job: models.Job,
    mineru: MinerUAdapter,
    raw_content: bytes,
    raw_payload: dict[str, Any] | None,
) -> tuple[
    models.DocumentAsset,
    models.DocumentVersion,
    models.ParseArtifact | None,
    models.NormalizedAssetRef,
]:
    job.status = JobStatus.RUNNING
    asset, version = _create_asset_and_version(session, raw_object, raw_payload)

    parse_artifact = None
    if _asset_kind_for(raw_object) == AssetKind.DOCUMENT:
        job.current_stage = "parse"
        parsed = mineru.parse(
            str(raw_object.metadata_summary.get("filename", raw_object.id)),
            raw_content,
            raw_object.mime_type,
        )
        parse_artifact = models.ParseArtifact(
            raw_object_id=raw_object.id,
            document_version_id=version.id,
            artifact_uri="pending",
            parse_mode=parsed.parse_mode,
            checksum=checksum_value(parsed.content),
            status=ParseArtifactStatus.GENERATED,
            metadata_summary=parsed.metadata,
        )
        session.add(parse_artifact)
        session.flush()
        stored = storage.put_bytes(
            _artifact_key(settings, version.id, parse_artifact.id),
            parsed.content,
            parsed.content_type,
            {"nexus-raw-object-id": raw_object.id, "nexus-version-id": version.id},
        )
        parse_artifact.artifact_uri = stored.object_uri
        try:
            parse_payload = json.loads(parsed.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parse_payload = {
                "schema_version": "mineru-raw-v1",
                "title": raw_object.metadata_summary.get("filename", raw_object.id),
                "markdown": parsed.content.decode("utf-8", errors="ignore")[:4000],
            }
        _add_stage(
            session,
            job,
            "parse",
            JobStatus.SUCCEEDED,
            {"parse_artifact_id": parse_artifact.id, "artifact_uri": parse_artifact.artifact_uri},
        )
        normalized_type = NormalizedType.DOCUMENT
        normalized_payload = _normalize_document(raw_object, parse_artifact, parse_payload)
    else:
        normalized_type = NormalizedType.RECORD
        normalized_payload = _normalize_record(raw_object, raw_payload or {})

    job.current_stage = "normalize"
    normalized_ref = _create_normalized_ref(
        session, storage, settings, version, normalized_type, normalized_payload
    )
    _add_stage(
        session,
        job,
        "normalize",
        JobStatus.SUCCEEDED,
        {"normalized_ref_id": normalized_ref.id, "normalized_uri": normalized_ref.object_uri},
    )
    version.metadata_summary = {
        **version.metadata_summary,
        "m1_ready_for_governance": True,
        "available_blocked_reason": "quality_governance_rules_not_run",
    }
    asset.metadata_summary = {
        **asset.metadata_summary,
        "m1_ready_for_governance": True,
        "available_blocked_reason": "quality_governance_rules_not_run",
    }
    _audit(
        session,
        AuditEventType.VERSION_STATUS_CHANGED,
        "document_version",
        version.id,
        job.trace_id,
        {
            "from_status": AssetVersionStatus.PROCESSING.value,
            "to_status": AssetVersionStatus.PROCESSING.value,
            "reason": "m1_ready_for_governance",
        },
    )
    job.current_stage = "assetize"
    _add_stage(
        session,
        job,
        "assetize",
        JobStatus.SUCCEEDED,
        {"asset_id": asset.id, "version_id": version.id},
    )
    job.status = JobStatus.SUCCEEDED
    job.current_stage = "completed"
    job.failure_reason = None
    return asset, version, parse_artifact, normalized_ref


def submit_file_ingest(
    session: Session,
    payload: IngestFileSubmit,
    storage: ObjectStorage | None = None,
    mineru: MinerUAdapter | None = None,
    settings: Settings | None = None,
    trace_id: str | None = None,
) -> IngestToAssetResult:
    settings = settings or get_settings()
    storage = storage or get_object_storage(settings)
    mineru = mineru or get_mineru_adapter(settings)
    data_source = session.get(models.DataSource, payload.data_source_id)
    if data_source is None:
        raise ValueError("data_source not found")

    content = base64.b64decode(payload.content_base64)
    content_checksum = checksum_value(content)
    batch, created = _find_or_create_batch(
        session,
        payload.data_source_id,
        payload.idempotency_key,
        data_source.source_type,
        payload.submitted_by_user_id,
        {"filename": payload.filename, "object_count": 1},
    )
    if not created:
        existing_raw = session.scalar(
            select(models.RawObject).where(models.RawObject.batch_id == batch.id)
        )
        existing_job = session.scalar(
            select(models.Job).where(models.Job.ingest_batch_id == batch.id)
        )
        if existing_raw is None and existing_job is not None:
            existing_raw = existing_job.raw_object
        return IngestToAssetResult(batch, existing_raw, existing_job, None, None, None, None)

    duplicate_raw = session.scalar(
        select(models.RawObject).where(
            models.RawObject.data_source_id == data_source.id,
            models.RawObject.checksum == content_checksum,
        )
    )
    if duplicate_raw is not None:
        batch.status = IngestBatchStatus.DUPLICATE_SKIPPED
        batch.summary = {
            **batch.summary,
            "duplicate_raw_object_id": duplicate_raw.id,
            "filename": payload.filename,
        }
        job = _create_job(session, batch, duplicate_raw, trace_id)
        job.status = JobStatus.SUCCEEDED
        job.current_stage = "duplicate_skipped"
        _add_stage(
            session,
            job,
            "duplicate_check",
            JobStatus.SUCCEEDED,
            {"duplicate_raw_object_id": duplicate_raw.id},
        )
        _audit(
            session,
            AuditEventType.INGEST_BATCH_SUBMITTED,
            "ingest_batch",
            batch.id,
            trace_id,
            {
                "idempotency_key": payload.idempotency_key,
                "duplicate_raw_object_id": duplicate_raw.id,
            },
        )
        session.commit()
        return IngestToAssetResult(batch, duplicate_raw, job, None, None, None, None)

    key = _raw_key(
        settings,
        data_source.source_type,
        data_source.id,
        payload.idempotency_key,
        content_checksum,
        payload.filename,
    )
    stored = storage.put_bytes(
        key,
        content,
        payload.content_type,
        {"nexus-data-source-id": data_source.id, "nexus-idempotency-key": payload.idempotency_key},
    )
    raw = models.RawObject(
        batch_id=batch.id,
        data_source_id=data_source.id,
        source_type=data_source.source_type,
        source_uri=payload.source_uri,
        object_uri=stored.object_uri,
        checksum=stored.checksum,
        mime_type=payload.content_type,
        size_bytes=stored.size_bytes,
        status=RawObjectStatus.RAW_PERSISTED,
        metadata_summary={"filename": payload.filename},
    )
    session.add(raw)
    session.flush()
    batch.status = IngestBatchStatus.RAW_PERSISTED
    job = _create_job(session, batch, raw, trace_id)
    _audit(
        session,
        AuditEventType.INGEST_BATCH_SUBMITTED,
        "ingest_batch",
        batch.id,
        trace_id,
        {"idempotency_key": payload.idempotency_key, "object_count": 1},
    )
    _audit(
        session,
        AuditEventType.RAW_OBJECT_PERSISTED,
        "raw_object",
        raw.id,
        trace_id,
        {"batch_id": batch.id, "checksum": raw.checksum, "size_bytes": raw.size_bytes},
    )
    if payload.process_now:
        try:
            asset, version, parse_artifact, ref = _process_raw_object(
                session, storage, settings, raw, job, mineru, content, None
            )
            batch.status = IngestBatchStatus.COMPLETED
        except Exception as exc:
            _fail_pipeline(session, job, batch, raw, job.current_stage or "process", exc, trace_id)
            session.commit()
            raise PipelineError("file ingest pipeline failed") from exc
    else:
        asset = version = parse_artifact = ref = None
    session.commit()
    return IngestToAssetResult(batch, raw, job, asset, version, parse_artifact, ref)


def submit_crawler_package(
    session: Session,
    payload: CrawlerPackageSubmit,
    storage: ObjectStorage | None = None,
    settings: Settings | None = None,
    trace_id: str | None = None,
) -> IngestToAssetResult:
    settings = settings or get_settings()
    storage = storage or get_object_storage(settings)
    data_source = session.get(models.DataSource, payload.data_source_id)
    if data_source is None:
        raise ValueError("data_source not found")

    content = _json_bytes(payload.package)
    content_checksum = checksum_value(content)
    batch, created = _find_or_create_batch(
        session,
        payload.data_source_id,
        payload.idempotency_key,
        data_source.source_type,
        payload.submitted_by_user_id,
        {"object_count": 1, "package_type": "crawler_json"},
    )
    if not created:
        existing_raw = session.scalar(
            select(models.RawObject).where(models.RawObject.batch_id == batch.id)
        )
        existing_job = session.scalar(
            select(models.Job).where(models.Job.ingest_batch_id == batch.id)
        )
        if existing_raw is None and existing_job is not None:
            existing_raw = existing_job.raw_object
        return IngestToAssetResult(batch, existing_raw, existing_job, None, None, None, None)

    duplicate_raw = session.scalar(
        select(models.RawObject).where(
            models.RawObject.data_source_id == data_source.id,
            models.RawObject.checksum == content_checksum,
        )
    )
    if duplicate_raw is not None:
        batch.status = IngestBatchStatus.DUPLICATE_SKIPPED
        batch.summary = {**batch.summary, "duplicate_raw_object_id": duplicate_raw.id}
        job = _create_job(session, batch, duplicate_raw, trace_id)
        job.status = JobStatus.SUCCEEDED
        job.current_stage = "duplicate_skipped"
        _add_stage(
            session,
            job,
            "duplicate_check",
            JobStatus.SUCCEEDED,
            {"duplicate_raw_object_id": duplicate_raw.id},
        )
        _audit(
            session,
            AuditEventType.INGEST_BATCH_SUBMITTED,
            "ingest_batch",
            batch.id,
            trace_id,
            {
                "idempotency_key": payload.idempotency_key,
                "duplicate_raw_object_id": duplicate_raw.id,
            },
        )
        session.commit()
        return IngestToAssetResult(batch, duplicate_raw, job, None, None, None, None)

    package_id = str(
        payload.package.get("id")
        or payload.package.get("source_id")
        or sha256_hex(content)[:16]
    )
    key = _raw_key(
        settings,
        data_source.source_type,
        data_source.id,
        payload.idempotency_key,
        content_checksum,
        f"{package_id}.json",
    )
    stored = storage.put_bytes(
        key,
        content,
        "application/json",
        {"nexus-data-source-id": data_source.id, "nexus-idempotency-key": payload.idempotency_key},
    )
    raw = models.RawObject(
        batch_id=batch.id,
        data_source_id=data_source.id,
        source_type=data_source.source_type,
        source_uri=payload.source_uri,
        object_uri=stored.object_uri,
        checksum=stored.checksum,
        mime_type="application/json",
        size_bytes=stored.size_bytes,
        status=RawObjectStatus.RAW_PERSISTED,
        metadata_summary={"package_id": package_id},
    )
    session.add(raw)
    session.flush()
    batch.status = IngestBatchStatus.RAW_PERSISTED
    job = _create_job(session, batch, raw, trace_id)
    _audit(
        session,
        AuditEventType.INGEST_BATCH_SUBMITTED,
        "ingest_batch",
        batch.id,
        trace_id,
        {"idempotency_key": payload.idempotency_key, "object_count": 1},
    )
    _audit(
        session,
        AuditEventType.RAW_OBJECT_PERSISTED,
        "raw_object",
        raw.id,
        trace_id,
        {"batch_id": batch.id, "checksum": raw.checksum, "size_bytes": raw.size_bytes},
    )
    if payload.process_now:
        try:
            asset, version, parse_artifact, ref = _process_raw_object(
                session, storage, settings, raw, job, FakeMinerUAdapter(), content, payload.package
            )
            batch.status = IngestBatchStatus.COMPLETED
        except Exception as exc:
            _fail_pipeline(session, job, batch, raw, job.current_stage or "process", exc, trace_id)
            session.commit()
            raise PipelineError("crawler ingest pipeline failed") from exc
    else:
        asset = version = parse_artifact = ref = None
    session.commit()
    return IngestToAssetResult(batch, raw, job, asset, version, parse_artifact, ref)


def list_jobs(session: Session) -> list[models.Job]:
    return list(session.scalars(select(models.Job).order_by(models.Job.created_at.desc())).all())


def list_job_stages(session: Session, job_id: str) -> list[models.JobStage]:
    return list(
        session.scalars(
            select(models.JobStage)
            .where(models.JobStage.job_id == job_id)
            .order_by(models.JobStage.created_at.asc())
        ).all()
    )


def list_assets(session: Session) -> list[models.DocumentAsset]:
    return list(
        session.scalars(
            select(models.DocumentAsset).order_by(models.DocumentAsset.created_at.desc())
        ).all()
    )


def list_asset_versions(session: Session, asset_id: str) -> list[models.DocumentVersion]:
    return list(
        session.scalars(
            select(models.DocumentVersion)
            .where(models.DocumentVersion.asset_id == asset_id)
            .order_by(models.DocumentVersion.version_no.desc())
        ).all()
    )


def get_current_version(
    session: Session, asset_id: str
) -> models.DocumentVersion | None:
    return session.scalar(
        select(models.DocumentVersion)
        .where(
            models.DocumentVersion.asset_id == asset_id,
            models.DocumentVersion.version_status == AssetVersionStatus.AVAILABLE,
        )
        .order_by(models.DocumentVersion.created_at.desc())
    )


def get_current_normalized_ref(
    session: Session, version_id: str
) -> models.NormalizedAssetRef | None:
    return session.scalar(
        select(models.NormalizedAssetRef)
        .where(
            models.NormalizedAssetRef.version_id == version_id,
            models.NormalizedAssetRef.status == NormalizedAssetRefStatus.GENERATED,
        )
        .order_by(models.NormalizedAssetRef.created_at.desc())
    )


def list_normalized_refs_for_versions(
    session: Session, version_ids: list[str]
) -> list[models.NormalizedAssetRef]:
    if not version_ids:
        return []
    return list(
        session.scalars(
            select(models.NormalizedAssetRef)
            .where(models.NormalizedAssetRef.version_id.in_(version_ids))
            .order_by(models.NormalizedAssetRef.created_at.desc())
        ).all()
    )
