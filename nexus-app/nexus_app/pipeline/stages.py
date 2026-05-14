from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import func, select

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    AuditEventType,
    NormalizedAssetRefStatus,
    NormalizedType,
    ParseArtifactStatus,
    PipelineType,
    StageStatus,
)
from nexus_app.ingest.keys import artifact_key, artifact_image_key, normalized_key
from nexus_app.pipeline import mineru_converter
from nexus_app.pipeline.context import PipelineContext
from nexus_app.storage import checksum_value

logger = logging.getLogger(__name__)


def _add_stage(
    ctx: PipelineContext,
    stage_name: str,
    status: StageStatus,
    detail: dict[str, Any] | None = None,
    failure_reason: str | None = None,
) -> models.JobStage:
    now = models.utcnow()
    stage = models.JobStage(
        job_id=ctx.job.id,
        stage_name=stage_name,
        status=status,
        started_at=now,
        finished_at=now if status in {StageStatus.SUCCEEDED, StageStatus.FAILED} else None,
        failure_reason=failure_reason,
        detail=detail or {},
    )
    ctx.job.current_stage = stage_name
    ctx.session.add(stage)
    ctx.session.flush()
    return stage


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
    """Stage 1 (both pipelines): Create or re-version DocumentAsset + DocumentVersion.

    Idempotency anchor: (data_source_id, source_object_key).
    - Same source_object_key, same checksum → caller should have skipped via duplicate check.
    - Same source_object_key, different checksum → archive old available, create version_no+1.
    - New source_object_key → create fresh asset at version_no=1.
    """
    raw_object = ctx.raw_object
    kind = AssetKind.RECORD if ctx.pipeline_type == PipelineType.RECORD else AssetKind.DOCUMENT
    source_key = (
        ctx.job.payload.get("source_object_key")
        or raw_object.source_uri
        or raw_object.id
    )

    existing_asset = ctx.session.scalar(
        select(models.DocumentAsset).where(
            models.DocumentAsset.data_source_id == raw_object.data_source_id,
            models.DocumentAsset.source_object_key == source_key,
        )
    )

    if existing_asset is not None:
        existing_available = ctx.session.scalars(
            select(models.DocumentVersion).where(
                models.DocumentVersion.asset_id == existing_asset.id,
                models.DocumentVersion.version_status == AssetVersionStatus.AVAILABLE,
            )
        ).all()
        for old_v in existing_available:
            old_v.version_status = AssetVersionStatus.ARCHIVED
            write_audit(
                ctx.session,
                AuditEventType.ASSET_VERSION_ARCHIVED,
                "document_version",
                old_v.id,
                ctx.trace_id,
                {
                    "asset_id": existing_asset.id,
                    "version_no": old_v.version_no,
                    "reason": "superseded_by_new_ingest",
                },
            )

        max_version_no = ctx.session.scalar(
            select(func.max(models.DocumentVersion.version_no)).where(
                models.DocumentVersion.asset_id == existing_asset.id,
            )
        ) or 0

        existing_asset.status = AssetVersionStatus.PROCESSING
        existing_asset.title = title_from(raw_object, raw_payload)
        ctx.session.flush()

        asset = existing_asset
        version_no = max_version_no + 1
    else:
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
        version_no = 1

    version = models.DocumentVersion(
        asset_id=asset.id,
        raw_object_id=raw_object.id,
        version_no=version_no,
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
        StageStatus.SUCCEEDED,
        {"asset_id": asset.id, "version_id": version.id, "version_no": version_no},
    )
    return asset, version


def run_parse(
    ctx: PipelineContext,
    version: models.DocumentVersion,
) -> models.ParseArtifact:
    """Stage 2 (Pipeline A only): Call MinerU, store artifact + images, create ParseArtifact."""
    if ctx.mineru is None:
        raise RuntimeError("run_parse called on a context without a MinerU adapter (record pipeline?)")

    raw_object = ctx.raw_object
    raw_uri = raw_object.object_uri
    raw_key = raw_uri.split("/", 3)[-1] if raw_uri.startswith("s3://") else raw_uri
    raw_content = ctx.storage.get_bytes(raw_key)

    filename = str(raw_object.metadata_summary.get("filename", raw_object.id))
    mime_type = raw_object.mime_type
    parsed = ctx.mineru.parse(filename, raw_content, mime_type)

    artifact = models.ParseArtifact(
        raw_object_id=raw_object.id,
        document_version_id=version.id,
        artifact_uri="pending",
        parse_mode=parsed.parse_mode,
        checksum=checksum_value(parsed.content),
        status=ParseArtifactStatus.GENERATED,
        metadata_summary={
            **parsed.metadata,
            "image_count": len(parsed.images),
        },
    )
    ctx.session.add(artifact)
    ctx.session.flush()

    stored = ctx.storage.put_bytes(
        artifact_key(ctx.settings, version.id, artifact.id),
        parsed.content,
        "application/json",
        {"nexus-raw-object-id": raw_object.id, "nexus-version-id": version.id},
    )
    artifact.artifact_uri = stored.object_uri

    # Store extracted images alongside the JSON result so renderers can resolve
    # image references in the middle-json without re-parsing the original file.
    image_uris: dict[str, str] = {}
    for img_name, img_bytes in parsed.images.items():
        img_key = artifact_image_key(ctx.settings, version.id, artifact.id, img_name)
        ext = img_name.rsplit(".", 1)[-1].lower() if "." in img_name else "bin"
        img_content_type = f"image/{ext}" if ext in {"png", "jpg", "jpeg", "webp", "gif", "tiff", "bmp"} else "application/octet-stream"
        img_stored = ctx.storage.put_bytes(
            img_key,
            img_bytes,
            img_content_type,
            {"nexus-artifact-id": artifact.id, "nexus-image-name": img_name},
        )
        image_uris[img_name] = img_stored.object_uri

    if image_uris:
        artifact.metadata_summary = {**artifact.metadata_summary, "image_uris": image_uris}

    ctx.session.flush()

    _add_stage(
        ctx,
        "parse",
        StageStatus.SUCCEEDED,
        {
            "parse_artifact_id": artifact.id,
            "artifact_uri": artifact.artifact_uri,
            "image_count": len(image_uris),
        },
    )
    return artifact


# ---------------------------------------------------------------------------
# Normalize — Pipeline A (document) and Pipeline B (record)
# ---------------------------------------------------------------------------

def run_normalize_document(
    ctx: PipelineContext,
    version: models.DocumentVersion,
    artifact: models.ParseArtifact,
) -> models.NormalizedAssetRef:
    """Stage 3 (Pipeline A): Build normalized_document from MinerU parse artifact."""
    raw_object = ctx.raw_object
    artifact_uri = artifact.artifact_uri
    artifact_key_path = artifact_uri.split("/", 3)[-1] if artifact_uri.startswith("s3://") else artifact_uri
    raw_bytes = ctx.storage.get_bytes(artifact_key_path)
    try:
        parse_payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        parse_payload = {
            "title": raw_object.metadata_summary.get("filename", raw_object.id),
            "markdown": raw_bytes.decode("utf-8", errors="ignore")[:4000],
        }
    normalized_payload = _build_normalized_document(raw_object, artifact, parse_payload, ctx)
    return _persist_normalized_ref(ctx, version, NormalizedType.DOCUMENT, normalized_payload)


def run_normalize_record(
    ctx: PipelineContext,
    version: models.DocumentVersion,
    raw_payload: dict[str, Any],
) -> models.NormalizedAssetRef:
    """Stage 3 (Pipeline B): Build normalized_record from raw JSON payload (no MinerU)."""
    normalized_payload = _build_normalized_record(ctx.raw_object, raw_payload)
    return _persist_normalized_ref(ctx, version, NormalizedType.RECORD, normalized_payload)


# ---------------------------------------------------------------------------
# Normalized payload builders
# ---------------------------------------------------------------------------

def _build_normalized_document(
    raw_object: models.RawObject,
    artifact: models.ParseArtifact,
    parse_payload: dict[str, Any],
    ctx: PipelineContext,
) -> dict[str, Any]:
    image_uris: dict[str, str] = artifact.metadata_summary.get("image_uris", {})

    pdf_info = parse_payload.get("pdf_info")
    if isinstance(pdf_info, list) and pdf_info:
        blocks, body_markdown = mineru_converter.convert(
            pdf_info,
            image_uris,
            ctx.image_analyzer,
            ctx.storage,
        )
    else:
        # Fallback: fake adapter or legacy format with top-level 'markdown'/'blocks'
        raw_md = parse_payload.get("markdown") or parse_payload.get("content") or ""
        body_markdown = str(raw_md)[:8000]
        raw_blocks = parse_payload.get("blocks")
        blocks = raw_blocks if isinstance(raw_blocks, list) else [{
            "block_id": "block-001",
            "block_type": "paragraph",
            "seq_no": 1,
            "text": body_markdown[:4000],
            "source_locator": {},
        }]

    return {
        "schema_version": "normalized-document-v1",
        "asset_id": None,
        "version_id": None,
        "source_type": raw_object.source_type.value,
        "source_ref": {
            "raw_object_id": raw_object.id,
            "raw_object_uri": raw_object.object_uri,
            "batch_id": raw_object.batch_id,
            "source_uri": raw_object.source_uri,
        },
        "content_type": "document",
        "title": title_from(raw_object, parse_payload),
        "language": "zh-CN",
        "toc": [],
        "blocks": blocks,
        "body_markdown": body_markdown,
        "attachments": _extract_attachments(artifact),
        "metadata": {
            "filename": raw_object.metadata_summary.get("filename"),
            "mime_type": raw_object.mime_type,
            "backend": artifact.metadata_summary.get("backend") or artifact.metadata_summary.get("model_version"),
            "ocr_enabled": artifact.metadata_summary.get("ocr_enabled", False),
        },
        "governance": {
            "sensitivity_level": None,
            "org_scope": [],
            "version_status": "processing",
        },
        "quality": {
            "parse_score": None,
            "normalize_score": None,
            "anomaly_items": [],
            "manual_review_status": "not_required",
        },
        "lineage": {
            "raw_object_id": raw_object.id,
            "raw_object_uri": raw_object.object_uri,
            "parse_artifact_id": artifact.id,
            "parse_artifact_uri": artifact.artifact_uri,
            "image_uris": image_uris,
        },
    }


def _extract_attachments(artifact: models.ParseArtifact) -> list[dict[str, Any]]:
    image_uris: dict[str, str] = artifact.metadata_summary.get("image_uris", {})
    return [
        {"attachment_type": "image", "filename": name, "uri": uri}
        for name, uri in image_uris.items()
    ]


def _build_normalized_record(
    raw_object: models.RawObject,
    raw_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "normalized-record-v1",
        "asset_id": None,
        "version_id": None,
        "source_type": raw_object.source_type.value,
        "record_type": raw_object.metadata_summary.get("record_type", "generic"),
        "record_key": raw_object.source_uri or raw_object.id,
        "title": title_from(raw_object, raw_payload),
        "language": "zh-CN",
        "record_body": raw_payload,
        "metadata": {
            "mime_type": raw_object.mime_type,
            "source_uri": raw_object.source_uri,
        },
        "governance": {
            "sensitivity_level": None,
            "org_scope": [],
            "version_status": "processing",
        },
        "quality": {
            "normalize_score": None,
            "anomaly_items": [],
            "manual_review_status": "not_required",
        },
        "lineage": {
            "raw_object_id": raw_object.id,
            "object_uri": raw_object.object_uri,
        },
    }


def _persist_normalized_ref(
    ctx: PipelineContext,
    version: models.DocumentVersion,
    normalized_type: NormalizedType,
    normalized_payload: dict[str, Any],
) -> models.NormalizedAssetRef:
    """Shared: back-fill IDs, store to MinIO, create NormalizedAssetRef, write audit."""
    normalized_payload["asset_id"] = version.asset_id
    normalized_payload["version_id"] = version.id

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
        source_type=ctx.raw_object.source_type.value,
        content_type=normalized_payload.get("content_type"),
        title=normalized_payload.get("title"),
        language=normalized_payload.get("language"),
        governance=normalized_payload.get("governance", {}),
        quality=normalized_payload.get("quality", {}),
        lineage=normalized_payload.get("lineage", {}),
        metadata_summary=normalized_payload.get("metadata", {}),
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
        StageStatus.SUCCEEDED,
        {"normalized_ref_id": ref.id, "normalized_uri": ref.object_uri},
    )
    return ref

