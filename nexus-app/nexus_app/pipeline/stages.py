from __future__ import annotations

import json
import logging
from datetime import datetime
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
    *,
    started_at: "datetime | None" = None,
) -> models.JobStage:
    """Record a finished stage row. If `started_at` is provided, the actual elapsed
    duration is preserved; otherwise the stage appears instantaneous.

    Stages that may take noticeable time (LLM calls, MinerU parse, RAGFlow submit)
    should call `_stage_started()` at entry and pass the timestamp here.
    """
    finished_at = models.utcnow()
    actual_start = started_at or finished_at
    terminal = status in {
        StageStatus.SUCCEEDED, StageStatus.FAILED,
        StageStatus.SKIPPED, StageStatus.PARTIAL,
    }
    stage = models.JobStage(
        job_id=ctx.job.id,
        stage_name=stage_name,
        status=status,
        started_at=actual_start,
        finished_at=finished_at if terminal else None,
        failure_reason=failure_reason,
        detail=detail or {},
    )
    ctx.job.current_stage = stage_name
    ctx.session.add(stage)
    ctx.session.flush()
    return stage


def _stage_started() -> "datetime":
    """Capture the start timestamp for a stage; pair with `_add_stage(started_at=...)`."""
    return models.utcnow()


def _begin_stage(
    ctx: PipelineContext,
    stage_name: str,
    detail: dict[str, Any] | None = None,
) -> models.JobStage:
    now = models.utcnow()
    stage = models.JobStage(
        job_id=ctx.job.id,
        stage_name=stage_name,
        status=StageStatus.RUNNING,
        started_at=now,
        finished_at=None,
        failure_reason=None,
        detail=detail or {},
    )
    ctx.job.current_stage = stage_name
    ctx.session.add(stage)
    ctx.session.flush()
    return stage


def _finish_stage(
    ctx: PipelineContext,
    stage: models.JobStage,
    status: StageStatus,
    detail: dict[str, Any] | None = None,
    failure_reason: str | None = None,
) -> models.JobStage:
    terminal = status in {
        StageStatus.SUCCEEDED, StageStatus.FAILED,
        StageStatus.SKIPPED, StageStatus.PARTIAL,
    }
    stage.status = status
    stage.finished_at = models.utcnow() if terminal else None
    stage.failure_reason = failure_reason[:2000] if failure_reason else None
    if detail is not None:
        stage.detail = detail
    ctx.job.current_stage = stage.stage_name
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


def _cleanup_storage_keys(ctx: PipelineContext, keys: list[str]) -> None:
    for key in reversed(keys):
        try:
            ctx.storage.delete_object(key)
        except Exception:
            logger.warning("failed to cleanup parse artifact object %s", key, exc_info=True)


def run_assetize(
    ctx: PipelineContext,
    raw_payload: dict[str, Any] | None = None,
) -> tuple[models.Asset, models.AssetVersion]:
    """Stage 1 (both pipelines): Create or re-version Asset + AssetVersion.

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
        select(models.Asset).where(
            models.Asset.data_source_id == raw_object.data_source_id,
            models.Asset.source_object_key == source_key,
        )
    )

    if existing_asset is not None:
        retry_version = ctx.session.scalar(
            select(models.AssetVersion)
            .where(
                models.AssetVersion.asset_id == existing_asset.id,
                models.AssetVersion.raw_object_id == raw_object.id,
                models.AssetVersion.source_checksum == raw_object.checksum,
                models.AssetVersion.version_status.in_(
                    [
                        AssetVersionStatus.PROCESSING,
                        AssetVersionStatus.FAILED,
                        AssetVersionStatus.REVIEW_REQUIRED,
                    ]
                ),
            )
            .order_by(models.AssetVersion.version_no.desc())
            .limit(1)
        )
        if retry_version is not None:
            existing_asset.status = AssetVersionStatus.PROCESSING
            existing_asset.title = title_from(raw_object, raw_payload)
            retry_version.version_status = AssetVersionStatus.PROCESSING
            retry_version.failure_reason = None
            retry_version.metadata_summary = {
                **(retry_version.metadata_summary or {}),
                "m1_ready_for_governance": False,
                "reused_for_retry": True,
            }
            ctx.session.flush()
            _add_stage(
                ctx,
                "assetize",
                StageStatus.SUCCEEDED,
                {
                    "asset_id": existing_asset.id,
                    "version_id": retry_version.id,
                    "version_no": retry_version.version_no,
                    "idempotent_reuse": True,
                },
            )
            return existing_asset, retry_version

        existing_available = ctx.session.scalars(
            select(models.AssetVersion).where(
                models.AssetVersion.asset_id == existing_asset.id,
                models.AssetVersion.version_status == AssetVersionStatus.AVAILABLE,
            )
        ).all()
        for old_v in existing_available:
            old_v.version_status = AssetVersionStatus.ARCHIVED
            write_audit(
                ctx.session,
                AuditEventType.ASSET_VERSION_ARCHIVED,
                "asset_version",
                old_v.id,
                ctx.trace_id,
                {
                    "asset_id": existing_asset.id,
                    "version_no": old_v.version_no,
                    "reason": "superseded_by_new_ingest",
                },
            )

        max_version_no = ctx.session.scalar(
            select(func.max(models.AssetVersion.version_no)).where(
                models.AssetVersion.asset_id == existing_asset.id,
            )
        ) or 0

        existing_asset.status = AssetVersionStatus.PROCESSING
        existing_asset.title = title_from(raw_object, raw_payload)
        ctx.session.flush()

        asset = existing_asset
        version_no = max_version_no + 1
    else:
        asset = models.Asset(
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

    version = models.AssetVersion(
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
    version: models.AssetVersion,
) -> models.ParseArtifact:
    """Stage 2 (Pipeline A only): Call MinerU, store artifact + images, create ParseArtifact.

    The MinerU HTTP call and object-storage writes intentionally run outside an
    open DB transaction. Only short DB state transitions are committed before
    and after the external work.
    """
    if ctx.mineru is None:
        raise RuntimeError("run_parse called on a context without a MinerU adapter (record pipeline?)")

    existing_artifact = ctx.session.scalar(
        select(models.ParseArtifact)
        .where(
            models.ParseArtifact.asset_version_id == version.id,
            models.ParseArtifact.status == ParseArtifactStatus.GENERATED,
        )
        .order_by(models.ParseArtifact.created_at.desc())
        .limit(1)
    )
    if existing_artifact is not None:
        _add_stage(
            ctx,
            "parse",
            StageStatus.SKIPPED,
            {
                "reason": "parse artifact already exists (idempotent reuse)",
                "parse_artifact_id": existing_artifact.id,
                "artifact_uri": existing_artifact.artifact_uri,
            },
        )
        return existing_artifact

    raw_object = ctx.raw_object
    raw_object_id = raw_object.id
    raw_uri = raw_object.object_uri
    filename = str(raw_object.metadata_summary.get("filename", raw_object.id))
    mime_type = raw_object.mime_type
    model_version_override = (ctx.job.payload or {}).get("model_version_override")
    version_id = version.id

    parse_stage = _begin_stage(
        ctx,
        "parse",
        {
            "filename": filename,
            "mime_type": mime_type,
            "raw_object_id": raw_object_id,
        },
    )
    parse_stage_id = parse_stage.id
    ctx.session.commit()

    # Do not touch ORM attributes in the long-running external block below.
    # After commit the Session holds no active DB transaction/connection until
    # the next DB operation, so MinerU and object-storage work stay outside DB
    # transaction scope while existing ORM instances remain attached for runner
    # outcome handling.

    stored_keys: list[str] = []
    artifact_id = models.new_uuid()
    try:
        raw_key = raw_uri.split("/", 3)[-1] if raw_uri.startswith("s3://") else raw_uri
        raw_content = ctx.storage.get_bytes(raw_key)

        parsed = ctx.mineru.parse(
            filename, raw_content, mime_type, model_version=model_version_override
        )

        artifact_storage_key = artifact_key(ctx.settings, version_id, artifact_id)
        stored = ctx.storage.put_bytes(
            artifact_storage_key,
            parsed.content,
            "application/json",
            {"nexus-raw-object-id": raw_object_id, "nexus-version-id": version_id},
        )
        stored_keys.append(artifact_storage_key)

        image_uris: dict[str, str] = {}
        for img_name, img_bytes in parsed.images.items():
            img_key = artifact_image_key(ctx.settings, version_id, artifact_id, img_name)
            ext = img_name.rsplit(".", 1)[-1].lower() if "." in img_name else "bin"
            img_content_type = f"image/{ext}" if ext in {"png", "jpg", "jpeg", "webp", "gif", "tiff", "bmp"} else "application/octet-stream"
            img_stored = ctx.storage.put_bytes(
                img_key,
                img_bytes,
                img_content_type,
                {"nexus-artifact-id": artifact_id, "nexus-image-name": img_name},
            )
            stored_keys.append(img_key)
            image_uris[img_name] = img_stored.object_uri
    except Exception as exc:
        _cleanup_storage_keys(ctx, stored_keys)
        parse_stage = ctx.session.get(models.JobStage, parse_stage_id)
        if parse_stage is not None:
            _finish_stage(
                ctx,
                parse_stage,
                StageStatus.FAILED,
                failure_reason=f"{type(exc).__name__}: {exc}",
            )
        raise

    artifact = models.ParseArtifact(
        id=artifact_id,
        raw_object_id=raw_object_id,
        asset_version_id=version_id,
        artifact_uri=stored.object_uri,
        parse_mode=parsed.parse_mode,
        checksum=checksum_value(parsed.content),
        status=ParseArtifactStatus.GENERATED,
        metadata_summary={
            **parsed.metadata,
            "image_count": len(parsed.images),
            **({"image_uris": image_uris} if image_uris else {}),
        },
    )

    try:
        ctx.session.add(artifact)
        parse_stage = ctx.session.get(models.JobStage, parse_stage_id)
        if parse_stage is None:
            raise RuntimeError(f"parse stage disappeared: {parse_stage_id}")
        _finish_stage(
            ctx,
            parse_stage,
            StageStatus.SUCCEEDED,
            {
                "parse_artifact_id": artifact.id,
                "artifact_uri": artifact.artifact_uri,
                "image_count": len(image_uris),
            },
        )
        ctx.session.flush()
    except Exception:
        ctx.session.rollback()
        _cleanup_storage_keys(ctx, stored_keys)
        raise

    return artifact


# ---------------------------------------------------------------------------
# Normalize — Pipeline A (document) and Pipeline B (record)
# ---------------------------------------------------------------------------

def run_normalize_document(
    ctx: PipelineContext,
    version: models.AssetVersion,
    artifact: models.ParseArtifact,
) -> models.NormalizedAssetRef:
    """Stage 3 (Pipeline A): Build normalized_document from MinerU parse artifact."""
    started_at = _stage_started()
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
    normalized_payload = _apply_normalize_service(
        ctx, normalized_payload, raw_object.source_type.value, "document"
    )
    return _persist_normalized_ref(
        ctx, version, NormalizedType.DOCUMENT, normalized_payload, started_at=started_at
    )


def run_normalize_record(
    ctx: PipelineContext,
    version: models.AssetVersion,
    raw_payload: dict[str, Any],
) -> models.NormalizedAssetRef:
    """Stage 3 (Pipeline B): Build normalized_record from raw JSON payload (no MinerU)."""
    started_at = _stage_started()
    normalized_payload = _build_normalized_record(ctx.raw_object, raw_payload)
    normalized_payload = _apply_normalize_service(
        ctx,
        normalized_payload,
        ctx.raw_object.source_type.value,
        ctx.raw_object.mime_type or "application/json",
    )
    return _persist_normalized_ref(
        ctx, version, NormalizedType.RECORD, normalized_payload, started_at=started_at
    )


def _apply_normalize_service(
    ctx: PipelineContext,
    normalized_payload: dict[str, Any],
    source_type: str,
    content_type: str,
) -> dict[str, Any]:
    """LLM + rule-engine fallback validation layer over the basic payload.

    Runs only when a NormalizeService is wired through PipelineContext (production
    path: lifespan-loaded registry + LiteLLM client). Issues found are appended
    to `payload.quality.normalize_issues` so AI governance can use them as
    blocking evidence; remaining issues do NOT fail the pipeline at this stage —
    governance decision is the authoritative gate.

    If no service is wired (e.g. test harnesses), the original payload is
    returned unchanged for backward compatibility.
    """
    service = ctx.normalize_service
    if service is None:
        return normalized_payload
    # Pipeline B content type may already be e.g. application/json; for documents
    # the normalize contract key uses the raw_object's MIME type.
    if content_type == "document":
        content_type = ctx.raw_object.mime_type or "application/octet-stream"
    try:
        result = service.normalize(
            normalized_payload,
            source_type=source_type,
            content_type=content_type,
        )
    except Exception as exc:  # noqa: BLE001  defensive: never let normalize service break pipeline
        logger.warning("NormalizeService raised %s; keeping pre-service payload", exc)
        return normalized_payload

    enhanced = dict(result.payload)
    quality = dict(enhanced.get("quality") or {})
    quality["normalize_contract_key"] = result.contract_key
    quality["normalize_schema_version"] = result.schema_version
    quality["normalize_llm_used"] = result.llm_used
    if result.llm_fallback_reason:
        quality["normalize_llm_fallback_reason"] = result.llm_fallback_reason
    if result.issues:
        quality["normalize_issues"] = [i.model_dump() for i in result.issues]
    enhanced["quality"] = quality
    return enhanced


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
    version: models.AssetVersion,
    normalized_type: NormalizedType,
    normalized_payload: dict[str, Any],
    *,
    started_at: datetime | None = None,
) -> models.NormalizedAssetRef:
    """Shared: back-fill IDs, store to MinIO, create NormalizedAssetRef, write audit."""
    existing_ref = ctx.session.scalar(
        select(models.NormalizedAssetRef)
        .where(
            models.NormalizedAssetRef.version_id == version.id,
            models.NormalizedAssetRef.status == NormalizedAssetRefStatus.GENERATED,
        )
        .order_by(models.NormalizedAssetRef.created_at.desc())
        .limit(1)
    )
    if existing_ref is not None:
        version.metadata_summary = {
            **(version.metadata_summary or {}),
            "m1_ready_for_governance": True,
            "normalized_ref_id": existing_ref.id,
        }
        _add_stage(
            ctx,
            "normalize",
            StageStatus.SKIPPED,
            {
                "reason": "normalized ref already exists (idempotent reuse)",
                "normalized_ref_id": existing_ref.id,
                "object_uri": existing_ref.object_uri,
            },
            started_at=started_at,
        )
        return existing_ref

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
        "asset_version",
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
        started_at=started_at,
    )
    return ref


# ---------------------------------------------------------------------------
# Governance Decision — runs after normalize for both pipelines
# ---------------------------------------------------------------------------

def run_governance_decision(
    ctx: PipelineContext,
    version: models.AssetVersion,
    normalized_ref: models.NormalizedAssetRef,
) -> models.GovernanceResult | None:
    """Stage 4 (both pipelines): AI governance + decision + version status transition.

    Returns None if no active prompt profile is configured (governance skipped).
    """
    started_at = _stage_started()
    from nexus_app.ai_governance.prompt_registry import (
        GovernancePromptNotFoundError,
        get_governance_prompt_registry,
    )
    from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry
    from nexus_app.ai_governance.services import AIGovernanceService
    from nexus_app.governance.decision_service import GovernanceDecisionService
    from nexus_app.metadata.version_state import VersionStateManager

    registry = GovernanceRulesRegistry()
    try:
        registry.load(ctx.session)
    except Exception as exc:
        logger.warning("Governance rules not available, skipping decision: %s", exc)
        _add_stage(ctx, "governance_decision", StageStatus.SKIPPED,
                   {"reason": f"rules not available: {exc}"},
                   started_at=started_at)
        return None

    prompt_registry = get_governance_prompt_registry()
    if not prompt_registry.is_loaded():
        try:
            prompt_registry.load(ctx.session)
        except Exception as exc:
            logger.warning(
                "Prompt registry not available, skipping governance: %s", exc
            )
            _add_stage(ctx, "governance_decision", StageStatus.SKIPPED,
                       {"reason": f"prompt registry not available: {exc}"},
                       started_at=started_at)
            return None

    try:
        prompt_registry.get_prompt("classification")
    except GovernancePromptNotFoundError:
        logger.info("No active governance prompt templates, skipping AI governance")
        _add_stage(ctx, "governance_decision", StageStatus.SKIPPED,
                   {"reason": "no active governance prompt templates"},
                   started_at=started_at)
        return None

    ai_svc = AIGovernanceService()
    ai_run = ai_svc.run_governance_multi(
        ctx.session,
        normalized_ref_id=normalized_ref.id,
        prompt_registry=prompt_registry,
        rules_registry=registry,
    )

    if ai_run.ai_output is None:
        logger.warning("AI governance run %s produced no output", ai_run.id)
        # Surface AI failure on the version so the workbench can show a manual
        # restart action; the job itself is left COMPLETED so the worker doesn't
        # auto-retry indefinitely once retries are exhausted upstream.
        version.version_status = AssetVersionStatus.FAILED
        version.failure_reason = (
            f"ai_governance_failed: {ai_run.validation_error or 'no ai_output'}"
        )[:2000]
        write_audit(
            ctx.session,
            AuditEventType.VERSION_STATUS_CHANGED,
            "asset_version", version.id, ctx.trace_id,
            {
                "from_status": AssetVersionStatus.PROCESSING.value,
                "to_status": AssetVersionStatus.FAILED.value,
                "reason": "ai_governance_failed",
                "ai_run_id": ai_run.id,
                "restartable": True,
            },
        )
        _add_stage(ctx, "governance_decision", StageStatus.FAILED,
                   {
                       "ai_run_id": ai_run.id,
                       "reason": "no ai_output",
                       "version_status": AssetVersionStatus.FAILED.value,
                       "restartable": True,
                   },
                   failure_reason=ai_run.validation_error,
                   started_at=started_at)
        return None

    decision_svc = GovernanceDecisionService(registry)
    result = decision_svc.execute_governance(ctx.session, ai_run)

    # Explicit emissions write: materializes knowledge_emissions on the ref so
    # downstream run_knowledge_chunking can find them. Best-effort; failures
    # are logged but don't block the version state transition.
    ai_svc.write_knowledge_emissions(ctx.session, ai_run, registry)

    state_mgr = VersionStateManager()
    target_status = state_mgr.determine_version_status(ctx.session, result)

    if target_status == AssetVersionStatus.AVAILABLE:
        state_mgr.transition_to_available(ctx.session, version, result)
    else:
        state_mgr.transition_to_review_required(ctx.session, version, result)

    _add_stage(
        ctx,
        "governance_decision",
        StageStatus.SUCCEEDED,
        {
            "ai_run_id": ai_run.id,
            "governance_result_id": result.id,
            "status": result.status.value,
            "version_status": version.version_status.value,
        },
        started_at=started_at,
    )
    return result


# ---------------------------------------------------------------------------
# Knowledge Chunking — Pipeline 5a: only for available assets with emissions
# ---------------------------------------------------------------------------

def run_knowledge_chunking(
    ctx: PipelineContext,
    version: models.AssetVersion,
    normalized_ref: models.NormalizedAssetRef,
) -> list[models.KnowledgeChunk]:
    """Stage 5a: Generate KnowledgeChunk records via Knowledge Pipeline.

    Skipped when:
    - version.version_status != available (only RAG-eligible assets)
    - normalized_ref.metadata_summary.knowledge_emissions is missing/empty
    """
    started_at = _stage_started()
    if version.version_status != AssetVersionStatus.AVAILABLE:
        _add_stage(ctx, "knowledge_chunking", StageStatus.SKIPPED,
                   {"reason": f"version not available (status={version.version_status.value})"},
                   started_at=started_at)
        return []

    emissions = (normalized_ref.metadata_summary or {}).get("knowledge_emissions", [])
    if not emissions:
        _add_stage(ctx, "knowledge_chunking", StageStatus.SKIPPED,
                   {"reason": "no knowledge_emissions on normalized_ref"},
                   started_at=started_at)
        return []

    # Idempotency: if chunks already exist for this ref (job retry), reuse them.
    existing = list(ctx.session.scalars(
        select(models.KnowledgeChunk).where(
            models.KnowledgeChunk.normalized_ref_id == normalized_ref.id
        )
    ).all())
    if existing:
        _add_stage(
            ctx,
            "knowledge_chunking",
            StageStatus.SKIPPED,
            {
                "reason": "chunks already exist (idempotent skip)",
                "existing_chunk_count": len(existing),
            },
            started_at=started_at,
        )
        return existing

    from nexus_app.knowledge.services import run_knowledge_pipeline

    content, content_blocks = _load_normalized_payload(ctx, normalized_ref)
    chunks = run_knowledge_pipeline(
        content, emissions, normalized_ref.id, content_blocks=content_blocks
    )
    for chunk in chunks:
        ctx.session.add(chunk)
    ctx.session.flush()

    _add_stage(
        ctx,
        "knowledge_chunking",
        StageStatus.SUCCEEDED,
        {
            "normalized_ref_id": normalized_ref.id,
            "emission_count": len(emissions),
            "chunk_count": len(chunks),
        },
        started_at=started_at,
    )
    return chunks


def _load_normalized_content(
    ctx: PipelineContext,
    normalized_ref: models.NormalizedAssetRef,
) -> str:
    """Read just the textual content from normalized payload.

    Retained for callers that do not need block locators (e.g. AI governance
    input building). For knowledge chunking use _load_normalized_payload to
    receive blocks alongside content.
    """
    content, _ = _load_normalized_payload(ctx, normalized_ref)
    return content


def _load_normalized_payload(
    ctx: PipelineContext,
    normalized_ref: models.NormalizedAssetRef,
) -> tuple[str, list[dict[str, Any]] | None]:
    """Read normalized payload and return ``(content, content_blocks)``.

    ``content`` is the canonical text passed into chunking strategies and
    LLM Prompt builders — byte-for-byte the value persisted in MinIO. Adding
    block-level locators here MUST NOT mutate ``content`` (see ARCHITECT
    "Chunk Locator Contract" and the md_char_range out-of-band rule).

    ``content_blocks`` is the ``normalized_document.blocks[]`` list when the
    payload describes a document; None for ``normalized_record`` payloads so
    record-type chunks correctly carry ``locator=None``.
    """
    uri = normalized_ref.object_uri
    key = uri.split("/", 3)[-1] if uri.startswith("s3://") else uri
    raw = ctx.storage.get_bytes(key)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return raw.decode("utf-8", errors="ignore"), None
    content = (
        payload.get("body_markdown")
        or json.dumps(payload.get("record_body", {}), ensure_ascii=False)
        or ""
    )
    blocks = payload.get("blocks")
    if isinstance(blocks, list) and blocks:
        return content, blocks
    return content, None


# ---------------------------------------------------------------------------
# Index Submit — Pipeline 5b: submit chunks to RAGFlow per emission
# ---------------------------------------------------------------------------

def run_index_submit(
    ctx: PipelineContext,
    version: models.AssetVersion,
    normalized_ref: models.NormalizedAssetRef,
    chunks: list[models.KnowledgeChunk],
) -> list[models.IndexManifest]:
    """Stage 5b: Submit chunks to RAGFlow per knowledge type, persist IndexManifest.

    Skipped when:
    - chunks is empty (knowledge chunking was skipped or produced nothing)
    - version is not available
    """
    started_at = _stage_started()
    if version.version_status != AssetVersionStatus.AVAILABLE:
        _add_stage(ctx, "index_submit", StageStatus.SKIPPED,
                   {"reason": f"version not available (status={version.version_status.value})"},
                   started_at=started_at)
        return []
    if not chunks:
        _add_stage(ctx, "index_submit", StageStatus.SKIPPED,
                   {"reason": "no knowledge chunks to index"},
                   started_at=started_at)
        return []

    from nexus_app.enums import IndexManifestStatus, ChunkType

    # Idempotency: load existing INDEXED manifests per knowledge_type so a
    # partial-success retry only re-attempts the kts that previously failed.
    existing_by_kt: dict[str, models.IndexManifest] = {
        m.knowledge_type_code: m
        for m in ctx.session.scalars(
            select(models.IndexManifest).where(
                models.IndexManifest.normalized_ref_id == normalized_ref.id,
                models.IndexManifest.index_status == IndexManifestStatus.INDEXED,
            )
        ).all()
    }

    from nexus_app.index.kb_registry import get_kb_registry
    from nexus_app.index.ragflow_adapter import get_ragflow_adapter
    from nexus_app.knowledge.config_loader import get_knowledge_type_config

    adapter = get_ragflow_adapter(ctx.settings)
    kb_registry = get_kb_registry()
    normalized_content = _load_normalized_content(ctx, normalized_ref)
    doc_name_base = (normalized_ref.title or normalized_ref.id)[:120]

    chunks_by_kt: dict[str, list[models.KnowledgeChunk]] = {}
    for chunk in chunks:
        chunks_by_kt.setdefault(chunk.knowledge_type_code, []).append(chunk)

    manifests: list[models.IndexManifest] = []
    error_messages: list[str] = []

    for kt_code, kt_chunks in chunks_by_kt.items():
        if kt_code in existing_by_kt:
            manifests.append(existing_by_kt[kt_code])
            continue
        try:
            kt_config = get_knowledge_type_config(kt_code)
            kb_id = kb_registry.ensure_kb(kt_code)
            chunk_method = kt_config.ragflow.get("chunk_method", "naive")
            parser_config = kt_config.ragflow.get("parser_config")

            is_passthrough = any(
                c.chunk_type == ChunkType.PASSTHROUGH_DESCRIPTOR for c in kt_chunks
            )
            doc_name = f"{doc_name_base}__{kt_code}"

            from nexus_app.index.ragflow_adapter import call_ragflow_with_retry

            # RAGFlow side idempotency: if a previous attempt created the doc
            # but failed before we could write the IndexManifest, reuse the
            # existing doc_id rather than creating a duplicate. Retriable on
            # transient errors via call_ragflow_with_retry.
            existing_doc = call_ragflow_with_retry(
                lambda: adapter.find_document_by_name(kb_id, doc_name),
                operation="find_document_by_name",
            )

            if is_passthrough:
                if existing_doc is not None:
                    doc_id = existing_doc["doc_id"]
                    logger.info(
                        "Reusing existing RAGFlow doc %s for kt=%s (idempotent)",
                        doc_id, kt_code,
                    )
                else:
                    doc_result = call_ragflow_with_retry(
                        lambda: adapter.create_document(
                            kb_id=kb_id,
                            doc_name=doc_name,
                            content=normalized_content,
                            chunk_method=chunk_method,
                            parser_config=parser_config,
                        ),
                        operation="create_document",
                    )
                    doc_id = doc_result["doc_id"]
                indexed_chunk_count = len(kt_chunks)
                for chunk in kt_chunks:
                    chunk.ragflow_doc_id = doc_id
                    metadata = dict(chunk.chunk_metadata or {})
                    metadata["ragflow_doc_id"] = doc_id
                    chunk.chunk_metadata = metadata
            else:
                if existing_doc is not None:
                    doc_id = existing_doc["doc_id"]
                    logger.info(
                        "Reusing existing RAGFlow doc %s for kt=%s (idempotent)",
                        doc_id, kt_code,
                    )
                    doc_result = {"doc_id": doc_id}
                else:
                    doc_result = call_ragflow_with_retry(
                        lambda: adapter.create_document(
                            kb_id=kb_id,
                            doc_name=doc_name,
                            content=None,
                            chunk_method=chunk_method,
                            parser_config=parser_config,
                        ),
                        operation="create_document",
                    )
                    doc_id = doc_result["doc_id"]
                submit_result = call_ragflow_with_retry(
                    lambda: adapter.submit_chunks(
                        kb_id=kb_id,
                        doc_id=doc_id,
                        chunks=kt_chunks,
                        chunk_method=chunk_method,
                    ),
                    operation="submit_chunks",
                )
                chunk_ids = submit_result.get("chunk_ids", [])
                indexed_chunk_count = len(chunk_ids)
                for idx, chunk in enumerate(kt_chunks):
                    chunk.ragflow_doc_id = doc_id
                    if idx < len(chunk_ids):
                        chunk.ragflow_chunk_id = chunk_ids[idx]

            manifest = models.IndexManifest(
                normalized_ref_id=normalized_ref.id,
                knowledge_type_code=kt_code,
                index_status=IndexManifestStatus.INDEXED,
                ragflow_kb_id=kb_id,
                ragflow_doc_id=doc_id,
                chunk_count=indexed_chunk_count,
                indexed_at=models.utcnow(),
                trace_id=ctx.trace_id,
            )
            ctx.session.add(manifest)
            ctx.session.flush()
            manifests.append(manifest)

        except Exception as exc:
            from nexus_app.index.ragflow_adapter import (
                RAGFlowAdapterError,
                RAGFlowErrorType,
            )
            error_type = (
                exc.error_type.value
                if isinstance(exc, RAGFlowAdapterError) and exc.error_type
                else RAGFlowErrorType.UNKNOWN.value
            )
            err = (
                f"index_submit failed for kt={kt_code} "
                f"[{error_type}]: {type(exc).__name__}: {exc}"
            )
            logger.warning(err)
            error_messages.append(err)
            manifest = models.IndexManifest(
                normalized_ref_id=normalized_ref.id,
                knowledge_type_code=kt_code,
                index_status=IndexManifestStatus.FAILED,
                ragflow_kb_id=kb_registry.get_cached(kt_code),
                chunk_count=0,
                error_message=err[:1000],
                trace_id=ctx.trace_id,
            )
            ctx.session.add(manifest)
            ctx.session.flush()
            manifests.append(manifest)

    indexed_count = sum(
        1 for m in manifests if m.index_status == IndexManifestStatus.INDEXED
    )
    failed_count = len(error_messages)
    if failed_count == 0:
        overall_status = StageStatus.SUCCEEDED
    elif indexed_count == 0:
        overall_status = StageStatus.FAILED
    else:
        overall_status = StageStatus.PARTIAL
    _add_stage(
        ctx,
        "index_submit",
        overall_status,
        {
            "normalized_ref_id": normalized_ref.id,
            "knowledge_types": list(chunks_by_kt.keys()),
            "manifest_count": len(manifests),
            "indexed_count": indexed_count,
            "failed_count": failed_count,
            "errors": error_messages,
        },
        failure_reason="; ".join(error_messages)[:1000] if error_messages else None,
        started_at=started_at,
    )
    return manifests

