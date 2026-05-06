from __future__ import annotations

import json
from typing import Any

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    AuditEventType,
    DataSourceType,
    JobStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    ParseArtifactStatus,
)
from nexus_app.ingest.keys import artifact_key, normalized_key
from nexus_app.pipeline.context import PipelineContext
from nexus_app.storage import checksum_value


def _add_stage(
    ctx: PipelineContext,
    stage_name: str,
    status: JobStatus,
    detail: dict[str, Any] | None = None,
    failure_reason: str | None = None,
) -> models.JobStage:
    now = models.utcnow()
    stage = models.JobStage(
        job_id=ctx.job.id,
        stage_name=stage_name,
        status=status,
        started_at=now,
        finished_at=now if status in {JobStatus.SUCCEEDED, JobStatus.FAILED} else None,
        failure_reason=failure_reason,
        detail=detail or {},
    )
    ctx.job.current_stage = stage_name
    ctx.session.add(stage)
    ctx.session.flush()
    return stage


def asset_kind_for(raw_object: models.RawObject) -> AssetKind:
    if raw_object.source_type in {
        DataSourceType.CRAWLER,
        DataSourceType.WEBHOOK,
        DataSourceType.DATABASE,
    }:
        return AssetKind.RECORD
    if raw_object.mime_type and "json" in raw_object.mime_type:
        return AssetKind.RECORD
    return AssetKind.DOCUMENT


def title_from(raw_object: models.RawObject, payload: dict[str, Any] | None = None) -> str:
    if payload:
        for key in ("title", "name", "source_title"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:256]
    filename = raw_object.metadata_summary.get("filename")
    if isinstance(filename, str) and filename:
        return filename[:256]
    return raw_object.id


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")


def run_assetize(
    ctx: PipelineContext,
    raw_payload: dict[str, Any] | None = None,
) -> tuple[models.DocumentAsset, models.DocumentVersion]:
    """Stage 1: Create DocumentAsset + DocumentVersion (processing state)."""
    raw_object = ctx.raw_object
    kind = asset_kind_for(raw_object)
    source_key = raw_object.source_uri or raw_object.object_uri

    asset = models.DocumentAsset(
        data_source_id=raw_object.data_source_id,
        source_object_key=source_key,
        title=title_from(raw_object, raw_payload),
        asset_kind=kind,
        status=AssetVersionStatus.PROCESSING,
        org_scope=[],
        metadata_summary={"source_type": raw_object.source_type.value},
    )
    ctx.session.add(asset)
    ctx.session.flush()

    version = models.DocumentVersion(
        asset_id=asset.id,
        raw_object_id=raw_object.id,
        version_no=1,
        version_status=AssetVersionStatus.PROCESSING,
        source_checksum=raw_object.checksum,
        metadata_summary={
            "m1_ready_for_governance": False,
        },
    )
    ctx.session.add(version)
    ctx.session.flush()

    _add_stage(
        ctx,
        "assetize",
        JobStatus.SUCCEEDED,
        {"asset_id": asset.id, "version_id": version.id},
    )
    return asset, version


def run_parse(
    ctx: PipelineContext,
    version: models.DocumentVersion,
) -> models.ParseArtifact:
    """Stage 2 (documents only): Call MinerU, store artifact, create ParseArtifact record."""
    raw_object = ctx.raw_object
    raw_uri = raw_object.object_uri
    raw_key = raw_uri.split("/", 3)[-1] if raw_uri.startswith("s3://") else raw_uri
    raw_content = ctx.storage.get_bytes(raw_key)

    filename = str(raw_object.metadata_summary.get("filename", raw_object.id))
    parsed = ctx.mineru.parse(filename, raw_content, raw_object.mime_type)

    artifact = models.ParseArtifact(
        raw_object_id=raw_object.id,
        document_version_id=version.id,
        artifact_uri="pending",
        parse_mode=parsed.parse_mode,
        checksum=checksum_value(parsed.content),
        status=ParseArtifactStatus.GENERATED,
        metadata_summary=parsed.metadata,
    )
    ctx.session.add(artifact)
    ctx.session.flush()

    stored = ctx.storage.put_bytes(
        artifact_key(ctx.settings, version.id, artifact.id),
        parsed.content,
        parsed.content_type,
        {"nexus-raw-object-id": raw_object.id, "nexus-version-id": version.id},
    )
    artifact.artifact_uri = stored.object_uri
    ctx.session.flush()

    _add_stage(
        ctx,
        "parse",
        JobStatus.SUCCEEDED,
        {"parse_artifact_id": artifact.id, "artifact_uri": artifact.artifact_uri},
    )
    return artifact


def _build_normalized_document(
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
        "title": title_from(raw_object, parse_payload),
        "source_type": raw_object.source_type.value,
        "blocks": blocks,
        "lineage": {
            "raw_object_id": raw_object.id,
            "raw_object_uri": raw_object.object_uri,
            "parse_artifact_id": artifact.id,
            "parse_artifact_uri": artifact.artifact_uri,
        },
    }


def _build_normalized_record(
    raw_object: models.RawObject,
    raw_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "normalized-record-v1",
        "source_type": raw_object.source_type.value,
        "record_key": raw_object.source_uri or raw_object.id,
        "title": title_from(raw_object, raw_payload),
        "record_body": raw_payload,
        "lineage": {"raw_object_id": raw_object.id, "object_uri": raw_object.object_uri},
    }


def run_normalize(
    ctx: PipelineContext,
    version: models.DocumentVersion,
    artifact: models.ParseArtifact | None,
    raw_payload: dict[str, Any] | None,
) -> models.NormalizedAssetRef:
    """Stage 3: Build normalized object, store it, create NormalizedAssetRef."""
    raw_object = ctx.raw_object
    kind = asset_kind_for(raw_object)

    if kind == AssetKind.DOCUMENT and artifact is not None:
        artifact_uri = artifact.artifact_uri
        artifact_key_path = artifact_uri.split("/", 3)[-1] if artifact_uri.startswith("s3://") else artifact_uri
        raw_bytes = ctx.storage.get_bytes(artifact_key_path)
        try:
            parse_payload = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parse_payload = {
                "schema_version": "mineru-raw-v1",
                "title": raw_object.metadata_summary.get("filename", raw_object.id),
                "markdown": raw_bytes.decode("utf-8", errors="ignore")[:4000],
            }
        normalized_type = NormalizedType.DOCUMENT
        normalized_payload = _build_normalized_document(raw_object, artifact, parse_payload)
    else:
        normalized_type = NormalizedType.RECORD
        normalized_payload = _build_normalized_record(raw_object, raw_payload or {})

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
    ctx.session.add(ref)
    ctx.session.flush()

    stored = ctx.storage.put_bytes(
        normalized_key(ctx.settings, normalized_type, version.id, ref.id, checksum),
        content,
        "application/json",
        {"nexus-version-id": version.id, "nexus-ref-id": ref.id},
    )
    ref.object_uri = stored.object_uri
    ctx.session.flush()

    version.metadata_summary = {
        **version.metadata_summary,
        "m1_ready_for_governance": True,
        "available_blocked_reason": "quality_governance_rules_not_run",
    }

    write_audit(
        ctx.session,
        AuditEventType.VERSION_STATUS_CHANGED,
        "document_version",
        version.id,
        ctx.trace_id,
        {
            "from_status": AssetVersionStatus.PROCESSING.value,
            "to_status": AssetVersionStatus.PROCESSING.value,
            "reason": "m1_ready_for_governance",
        },
    )

    _add_stage(
        ctx,
        "normalize",
        JobStatus.SUCCEEDED,
        {"normalized_ref_id": ref.id, "normalized_uri": ref.object_uri},
    )
    return ref
