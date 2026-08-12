from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote

from sqlalchemy import func, select

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.crawler.html_content_extractor import (
    PARSER_BACKEND as HTML_CONTENT_PARSER_BACKEND,
    build_markdown_sections,
    extract_html_main_content,
)
from nexus_app.enums import (
    AIGovernanceRunValidationStatus,
    AssetKind,
    AssetVersionStatus,
    AuditEventType,
    DataSourceType,
    GovernanceResultStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    ParseArtifactStatus,
    PipelineType,
    StageStatus,
)
from nexus_app.ingest.keys import artifact_key, artifact_image_key, normalized_key
from nexus_app.pipeline import mineru_converter
from nexus_app.pipeline.context import PipelineContext
from nexus_app.pipeline.normalized_record_schema import (
    NORMALIZED_DOCUMENT_SCHEMA_VERSION,
    NORMALIZED_RECORD_SCHEMA_VERSION,
)
from nexus_app.structured_parse.record_body_adapter import project_to_record_body
from nexus_app.storage import checksum_value

logger = logging.getLogger(__name__)


# This marker is persisted with parse-stage diagnostics.  It lets operators
# distinguish a Worker that has loaded the WebSearch package guard from a
# stale process without logging raw content.
WEB_DOCUMENT_ROUTE_RESOLVER_VERSION = "web-document-route-v2"
WEBSEARCH_CUSTOM_DOCUMENT_SCHEMA_VERSION = "websearch-custom-document.v1"


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


def get_pgvector_embedding_client(settings):
    from nexus_app.index.embedding_client import create_embedding_client

    return create_embedding_client(settings)


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
    metadata = raw_object.metadata_summary or {}
    if metadata.get("connector_type") == "websearch_custom_document":
        title = metadata.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()[:256]
    filename = metadata.get("filename")
    if isinstance(filename, str) and filename:
        return filename[:256]
    return raw_object.id


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _s3_metadata_value(value: str) -> str:
    """Encode arbitrary MinerU archive paths for ASCII-only S3 metadata."""
    return quote(value, safe="/._-")


def _cleanup_storage_keys(ctx: PipelineContext, keys: list[str]) -> None:
    for key in reversed(keys):
        try:
            ctx.storage.delete_object(key)
        except Exception:
            logger.warning("failed to cleanup parse artifact object %s", key, exc_info=True)


def _extract_markdown_blocks(content: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    parts = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
    for part in parts:
        heading = re.match(r"^(#{1,6})\s+(.+)$", part)
        if heading:
            level = len(heading.group(1))
            text = heading.group(2).strip()
            blocks.append({
                "tag": f"h{level}",
                "block_type": "heading",
                "heading_level": level,
                "text": text,
                "markdown": f"{'#' * level} {text}",
                "dom_path": None,
            })
        else:
            block_type = "list" if part.lstrip().startswith(("- ", "* ")) else "paragraph"
            blocks.append({
                "tag": "markdown",
                "block_type": block_type,
                "heading_level": None,
                "text": part,
                "markdown": part,
                "dom_path": None,
            })
    return blocks


def _materialize_web_blocks(
    extracted_blocks: list[dict[str, Any]],
    *,
    source_url: str | None,
    representation: str,
) -> tuple[str, list[dict[str, Any]]]:
    md_parts = [str(block.get("markdown") or block.get("text") or "").strip() for block in extracted_blocks]
    md_parts = [part for part in md_parts if part]
    body_markdown = "\n\n".join(md_parts)
    blocks: list[dict[str, Any]] = []
    cursor = 0
    for seq, (raw_block, md_part) in enumerate(zip(extracted_blocks, md_parts, strict=False), start=1):
        start = body_markdown.find(md_part, cursor)
        if start < 0:
            start = cursor
        end = start + len(md_part)
        cursor = end
        block_id = f"web-block-{seq:04d}"
        block = {
            "block_id": block_id,
            "block_type": raw_block.get("block_type") or "paragraph",
            "seq_no": seq,
            "text": raw_block.get("text") or md_part,
            "md_char_range": [start, end],
            "source_locator": {
                "locator_type": "markdown_range",
                "source_url": source_url,
                "raw_representation": representation,
                "dom_path": raw_block.get("dom_path"),
                "dom_index": seq,
                "md_char_range": [start, end],
            },
            "source_url": source_url,
            "dom_path": raw_block.get("dom_path"),
            "dom_index": seq,
            "locator_type": "markdown_range",
            "metadata": {
                "source": "firecrawl",
                "raw_representation": representation,
                "html_tag": raw_block.get("tag"),
            },
        }
        if raw_block.get("heading_level"):
            block["heading_level"] = raw_block["heading_level"]
        blocks.append(block)
    return body_markdown, blocks


def _websearch_package_header(raw_content: bytes | None) -> dict[str, Any] | None:
    """Return the non-content identity fields of a WebSearch raw package.

    Database metadata is convenient for routing, but it is not the immutable
    source of truth: historical rows or a partial metadata update must not
    cause a WebSearch JSON package to fall through to MinerU.  The package
    schema is deliberately strict so unrelated JSON uploads keep their normal
    pipeline behavior.
    """
    if raw_content is None:
        return None
    try:
        package = json.loads(raw_content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError):
        return None
    if not isinstance(package, dict):
        return None
    if (
        package.get("schema_version") != WEBSEARCH_CUSTOM_DOCUMENT_SCHEMA_VERSION
        or package.get("connector_type") != "websearch"
        or package.get("connector_version") != "custom"
    ):
        return None
    return package


def _web_document_route(
    raw_object: models.RawObject,
    raw_content: bytes | None = None,
) -> tuple[str | None, str]:
    """Resolve a document parser from current-object metadata and raw schema.

    The return value contains the route and its evidence source.  It is called
    for every job execution; no parser route is retained in the Worker or
    MinerU adapter between jobs.
    """
    metadata = raw_object.metadata_summary or {}
    mime_type = (raw_object.mime_type or "").lower()
    if (
        metadata.get("connector_type") == "websearch_custom_document"
        and mime_type in {"application/json", "application/vnd.nexus.websearch-custom-document+json"}
    ):
        return "websearch_custom_document", "raw_metadata"
    if (
        mime_type in {"application/json", "application/vnd.nexus.websearch-custom-document+json"}
        and _websearch_package_header(raw_content) is not None
    ):
        return "websearch_custom_document", "raw_package_schema"
    if (
        metadata.get("connector_type") == "firecrawl_document"
        and metadata.get("content_kind") == "web_document"
        and mime_type in {"text/html", "text/markdown"}
    ):
        return "firecrawl_web_document", "raw_metadata"
    return None, "none"


def _is_firecrawl_web_document(raw_object: models.RawObject) -> bool:
    """Compatibility predicate for callers that have metadata only."""
    return _web_document_route(raw_object)[0] is not None


def _parse_route_detail(
    raw_object: models.RawObject,
    route: str | None,
    *,
    route_evidence: str,
) -> dict[str, Any]:
    metadata = raw_object.metadata_summary or {}
    source_type = raw_object.source_type
    source_type_value = source_type.value if hasattr(source_type, "value") else str(source_type)
    return {
        "parse_route": route or "mineru",
        "route_evidence": route_evidence,
        "route_resolver_version": WEB_DOCUMENT_ROUTE_RESOLVER_VERSION,
        "source_type": source_type_value,
        "connector_type": metadata.get("connector_type"),
        "content_kind": metadata.get("content_kind"),
        "raw_representation": metadata.get("raw_representation"),
    }


def _ensure_document_heading(
    *,
    title: str,
    body_markdown: str,
    blocks: list[dict[str, Any]],
    source_url: str | None,
    representation: str,
    parser_backend: str,
) -> tuple[str, list[dict[str, Any]]]:
    if not title or any(
        block.get("block_type") == "heading" and block.get("heading_level") == 1
        for block in blocks
    ):
        return body_markdown, blocks

    heading_markdown = f"# {title[:256]}"
    prefix = f"{heading_markdown}\n\n" if body_markdown else heading_markdown
    shift = len(prefix)
    shifted: list[dict[str, Any]] = []
    for block in blocks:
        copy_block = dict(block)
        if isinstance(copy_block.get("seq_no"), int):
            copy_block["seq_no"] = int(copy_block["seq_no"]) + 1
        if _is_md_range(copy_block.get("md_char_range")):
            copy_block["md_char_range"] = [
                copy_block["md_char_range"][0] + shift,
                copy_block["md_char_range"][1] + shift,
            ]
        locator = dict(copy_block.get("source_locator") or {})
        if _is_md_range(locator.get("md_char_range")):
            locator["md_char_range"] = [
                locator["md_char_range"][0] + shift,
                locator["md_char_range"][1] + shift,
            ]
        copy_block["source_locator"] = locator
        shifted.append(copy_block)

    heading_block = {
        "block_id": "web-block-0000",
        "block_type": "heading",
        "seq_no": 1,
        "text": title[:256],
        "heading_level": 1,
        "md_char_range": [0, len(heading_markdown)],
        "source_locator": {
            "locator_type": "markdown_range",
            "source_url": source_url,
            "raw_representation": representation,
            "md_char_range": [0, len(heading_markdown)],
            "block_id": "web-block-0000",
            "section_id": shifted[0].get("section_id") if shifted else None,
        },
        "source_url": source_url,
        "dom_path": "synthetic/title",
        "dom_index": None,
        "locator_type": "markdown_range",
        "section_id": shifted[0].get("section_id") if shifted else None,
        "metadata": {
            "source": "firecrawl",
            "raw_representation": representation,
            "parser_backend": parser_backend,
            "locator_type": "markdown_range",
        },
    }
    return f"{prefix}{body_markdown}", [heading_block, *shifted]


def _is_md_range(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(item, int) for item in value)
    )


def _build_firecrawl_parse_payload(
    raw_object: models.RawObject,
    raw_content: bytes,
    *,
    route: str,
) -> dict[str, Any]:
    metadata = raw_object.metadata_summary or {}
    mime_type = (raw_object.mime_type or "").lower()
    source_text = raw_content.decode("utf-8", errors="replace")
    websearch_package = _websearch_package_header(raw_content) if route == "websearch_custom_document" else None
    if websearch_package is not None:
        try:
            source_text = str(websearch_package.get("content") or "")
        except (ValueError, TypeError):
            source_text = ""
    representation = "html" if mime_type == "text/html" else "markdown"
    source_url = metadata.get("canonical_url") or metadata.get("final_url") or metadata.get("source_url") or (websearch_package or {}).get("source_url") or raw_object.source_uri
    title = str(metadata.get("title") or (websearch_package or {}).get("title") or metadata.get("filename") or raw_object.id).strip()
    parser_backend = "websearch-custom-markdown-document-v1" if route == "websearch_custom_document" else "firecrawl-markdown-document-v1"
    sections: list[dict[str, Any]] = []
    retrieval_hints: dict[str, Any] = {}
    removed_noise: list[str] = []
    quality: dict[str, Any] = {"locator_quality": "markdown_range", "quality_flags": []}

    if representation == "html":
        parsed = extract_html_main_content(
            html=source_text,
            source_url=source_url,
            title_hint=title,
            metadata_hint=metadata,
        )
        title = parsed.title or title
        body_markdown = parsed.markdown
        blocks = parsed.blocks
        sections = parsed.sections
        retrieval_hints = parsed.retrieval_hints
        removed_noise = parsed.removed_noise
        quality = parsed.quality
        parser_backend = HTML_CONTENT_PARSER_BACKEND
    else:
        extracted_blocks = _extract_markdown_blocks(source_text)
        if title and not any(
            block.get("block_type") == "heading" and block.get("heading_level") == 1
            for block in extracted_blocks
        ):
            extracted_blocks.insert(0, {
                "tag": "h1",
                "block_type": "heading",
                "heading_level": 1,
                "text": title[:256],
                "markdown": f"# {title[:256]}",
                "dom_path": "synthetic/title",
            })
        body_markdown, blocks = _materialize_web_blocks(
            extracted_blocks,
            source_url=source_url,
            representation=representation,
        )
        sections = build_markdown_sections(blocks)
        for section in sections:
            for block in blocks:
                if section["start_seq_no"] <= block["seq_no"] <= section["end_seq_no"]:
                    block["section_id"] = section["section_id"]
                    block["source_locator"]["section_id"] = section["section_id"]
            section.pop("start_seq_no", None)
            section.pop("end_seq_no", None)
    heading_missing = bool(title) and not any(
        block.get("block_type") == "heading" and block.get("heading_level") == 1
        for block in blocks
    )
    heading_prefix = ""
    if heading_missing:
        heading_markdown = f"# {title[:256]}"
        heading_prefix = f"{heading_markdown}\n\n" if body_markdown else heading_markdown
    heading_shift = len(heading_prefix)
    body_markdown, blocks = _ensure_document_heading(
        title=title,
        body_markdown=body_markdown,
        blocks=blocks,
        source_url=source_url,
        representation=representation,
        parser_backend=parser_backend,
    )
    if heading_shift:
        for section in sections:
            md_range = section.get("md_char_range")
            if _is_md_range(md_range):
                section["md_char_range"] = [md_range[0] + heading_shift, md_range[1] + heading_shift]
    if not body_markdown:
        body_markdown = source_text.strip()
        blocks = []

    return {
        "schema_version": "firecrawl-web-document-v1",
        "parser_backend": parser_backend,
        "title": title[:256],
        "markdown": body_markdown,
        "content": body_markdown,
        "blocks": blocks or [{
            "block_id": "web-block-0001",
            "block_type": "paragraph",
            "seq_no": 1,
            "text": body_markdown[:4000],
            "md_char_range": [0, min(len(body_markdown), 4000)],
            "source_locator": {
                "locator_type": "markdown_range",
                "source_url": source_url,
                "raw_representation": representation,
                "dom_path": None,
                "dom_index": 1,
                "md_char_range": [0, min(len(body_markdown), 4000)],
            },
            "source_url": source_url,
            "dom_path": None,
            "dom_index": 1,
            "locator_type": "markdown_range",
            "metadata": {
                "source": "firecrawl",
                "raw_representation": representation,
                "parser_backend": parser_backend,
                "locator_type": "markdown_range",
            },
        }],
        "sections": sections,
        "retrieval_hints": retrieval_hints,
        "removed_noise": removed_noise,
        "quality": quality,
        "source": {
            "connector_type": metadata.get("connector_type") or "firecrawl_document",
            "content_kind": "web_document",
            "source_url": metadata.get("source_url"),
            "final_url": metadata.get("final_url"),
            "canonical_url": metadata.get("canonical_url"),
            "crawler_plan_id": metadata.get("crawler_plan_id"),
            "crawler_run_id": metadata.get("crawler_run_id"),
        },
    }


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
        asset_content_fingerprint = (raw_object.metadata_summary or {}).get(
            "asset_content_fingerprint"
        )
        if isinstance(asset_content_fingerprint, str) and asset_content_fingerprint:
            matching_version = next(
                (
                    candidate
                    for candidate in ctx.session.scalars(
                        select(models.AssetVersion)
                        .where(models.AssetVersion.asset_id == existing_asset.id)
                        .order_by(models.AssetVersion.version_no.desc())
                    ).all()
                    if (candidate.metadata_summary or {}).get("asset_content_fingerprint")
                    == asset_content_fingerprint
                    and candidate.version_status in {
                        AssetVersionStatus.AVAILABLE,
                        AssetVersionStatus.REVIEW_REQUIRED,
                        AssetVersionStatus.PROCESSING,
                    }
                ),
                None,
            )
            if matching_version is not None:
                _add_stage(
                    ctx,
                    "assetize",
                    StageStatus.SKIPPED,
                    {
                        "reason": "asset content fingerprint already processed",
                        "asset_id": existing_asset.id,
                        "version_id": matching_version.id,
                        "version_no": matching_version.version_no,
                        "asset_duplicate": True,
                        "asset_content_fingerprint": asset_content_fingerprint,
                    },
                )
                return existing_asset, matching_version

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
            **(
                {"asset_content_fingerprint": raw_object.metadata_summary["asset_content_fingerprint"]}
                if (raw_object.metadata_summary or {}).get("asset_content_fingerprint")
                else {}
            ),
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
    route, route_evidence = _web_document_route(raw_object)
    parse_route_detail = _parse_route_detail(
        raw_object,
        route,
        route_evidence=route_evidence,
    )
    model_version_override = (ctx.job.payload or {}).get("model_version_override")
    version_id = version.id

    parse_stage = _begin_stage(
        ctx,
        "parse",
        {
            "filename": filename,
            "mime_type": mime_type,
            "raw_object_id": raw_object_id,
            **parse_route_detail,
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

        # Re-resolve after reading MinIO.  This is the final execution
        # boundary: a valid WebSearch package must never be sent to MinerU,
        # even if its persisted metadata was produced by an older writer or
        # was subsequently reduced.
        route, route_evidence = _web_document_route(raw_object, raw_content)
        parse_route_detail = _parse_route_detail(
            raw_object,
            route,
            route_evidence=route_evidence,
        )
        parse_stage = ctx.session.get(models.JobStage, parse_stage_id)
        if parse_stage is None:
            raise RuntimeError(f"parse stage disappeared: {parse_stage_id}")
        parse_stage.detail = {
            "filename": filename,
            "mime_type": mime_type,
            "raw_object_id": raw_object_id,
            **parse_route_detail,
        }
        ctx.session.flush()
        logger.info(
            "parse route resolved job=%s raw_object=%s route=%s evidence=%s resolver=%s",
            ctx.job.id,
            raw_object_id,
            route or "mineru",
            route_evidence,
            WEB_DOCUMENT_ROUTE_RESOLVER_VERSION,
        )

        if route is not None:
            parse_payload = _build_firecrawl_parse_payload(
                raw_object,
                raw_content,
                route=route,
            )
            parsed_content = _json_bytes(parse_payload)
            parse_mode = route
            parsed_metadata = {
                "backend": "websearch-custom-document" if route == "websearch_custom_document" else "firecrawl-web-document",
                "model_version": "websearch-custom-document-v1" if route == "websearch_custom_document" else "firecrawl-web-document-v1",
                "parser_backend": parse_payload.get("parser_backend"),
                "ocr_enabled": False,
                "source_format": (raw_object.metadata_summary or {}).get("raw_representation")
                or ("html" if (mime_type or "").lower() == "text/html" else "markdown"),
                "source_url": (raw_object.metadata_summary or {}).get("source_url"),
                "final_url": (raw_object.metadata_summary or {}).get("final_url"),
                "canonical_url": (raw_object.metadata_summary or {}).get("canonical_url"),
            }
            parsed_images: dict[str, bytes] = {}
        else:
            if ctx.mineru is None:
                raise RuntimeError("run_parse called on a context without a MinerU adapter (record pipeline?)")
            parsed = ctx.mineru.parse(
                filename, raw_content, mime_type, model_version=model_version_override
            )
            parsed_content = parsed.content
            parse_mode = parsed.parse_mode
            parsed_metadata = parsed.metadata
            parsed_images = parsed.images

        artifact_storage_key = artifact_key(ctx.settings, version_id, artifact_id)
        stored = ctx.storage.put_bytes(
            artifact_storage_key,
            parsed_content,
            "application/json",
            {"nexus-raw-object-id": raw_object_id, "nexus-version-id": version_id},
        )
        stored_keys.append(artifact_storage_key)

        image_uris: dict[str, str] = {}
        for img_name, img_bytes in parsed_images.items():
            img_key = artifact_image_key(ctx.settings, version_id, artifact_id, img_name)
            ext = img_name.rsplit(".", 1)[-1].lower() if "." in img_name else "bin"
            img_content_type = f"image/{ext}" if ext in {"png", "jpg", "jpeg", "webp", "gif", "tiff", "bmp"} else "application/octet-stream"
            img_stored = ctx.storage.put_bytes(
                img_key,
                img_bytes,
                img_content_type,
                {
                    "nexus-artifact-id": artifact_id,
                    "nexus-image-name": _s3_metadata_value(img_name),
                },
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
                detail=parse_route_detail,
                failure_reason=f"{type(exc).__name__}: {exc}",
            )
        raise

    artifact = models.ParseArtifact(
        id=artifact_id,
        raw_object_id=raw_object_id,
        asset_version_id=version_id,
        artifact_uri=stored.object_uri,
        parse_mode=parse_mode,
        checksum=checksum_value(parsed_content),
        status=ParseArtifactStatus.GENERATED,
        metadata_summary={
            **parsed_metadata,
            "image_count": len(parsed_images),
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
                **parse_route_detail,
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

    # The MinerU-to-normalized conversion can call the visual VLM and object
    # storage. Snapshot the ORM fields it needs before releasing parse writes;
    # the external block below must not lazily reload them into a transaction.
    raw_snapshot = SimpleNamespace(
        id=raw_object.id,
        metadata_summary=dict(raw_object.metadata_summary or {}),
        mime_type=raw_object.mime_type,
        source_type=raw_object.source_type,
        object_uri=raw_object.object_uri,
        batch_id=raw_object.batch_id,
        source_uri=raw_object.source_uri,
    )
    artifact_snapshot = SimpleNamespace(
        id=artifact.id,
        metadata_summary=dict(artifact.metadata_summary or {}),
        artifact_uri=artifact.artifact_uri,
    )
    ctx.session.commit()
    raw_bytes = ctx.storage.get_bytes(artifact_key_path)
    try:
        parse_payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        parse_payload = {
            "title": raw_object.metadata_summary.get("filename", raw_object.id),
            "markdown": raw_bytes.decode("utf-8", errors="ignore")[:4000],
        }
    normalized_payload = _build_normalized_document(
        raw_snapshot, artifact_snapshot, parse_payload, ctx
    )
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
    *,
    profile_dict: dict[str, Any] | None = None,
) -> models.NormalizedAssetRef:
    """Stage 3 (Pipeline B): Build normalized_record from raw JSON payload (no MinerU).

    Args:
        profile_dict: Optional `ProfileDetectResult.model_dump(mode='json')`
            produced by `profile_detect` (B2.3). When provided, it is written
            into the normalized payload's `profile` field AND mirrored into
            `metadata.profile` so it propagates to
            `NormalizedAssetRef.metadata_summary["profile"]` for search /
            review consumers without forcing them to fetch the MinIO payload.

            The JSON path (`_load_record_payload`) passes `None` — profile
            detection is a structured_parse follow-on and doesn't fire on
            free-form JSON ingestion contracts.
    """
    started_at = _stage_started()
    normalized_payload = _build_normalized_record(
        ctx.raw_object, raw_payload, profile_dict=profile_dict
    )
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
        # The payload is entirely in memory at this point. Release writes from
        # assetize/parse and any read transaction before the synchronous LLM
        # request so the job heartbeat is never blocked by this session.
        ctx.session.commit()
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

def _make_pdf_renderer(
    raw_object: models.RawObject,
    storage: Any,
) -> "mineru_converter.PdfPageRenderer | None":
    """Build a PDF-page rasteriser used by mineru_converter to rescue
    image_only multi-page tables. Returns None for non-PDF sources or when
    pypdfium2 is not importable (keeps the converter happy without the dep).
    """
    mime = (raw_object.mime_type or "").lower()
    if "pdf" not in mime:
        return None
    try:
        import pypdfium2 as pdfium  # type: ignore[import-not-found]
    except ImportError:
        return None

    raw_key = (
        raw_object.object_uri.split("/", 3)[-1]
        if raw_object.object_uri.startswith("s3://")
        else raw_object.object_uri
    )
    # Load + decode the PDF once; the renderer closure renders specific pages
    # on demand. PdfDocument keeps the PDFium handle alive for the worker's
    # normalize step (short-lived).
    raw_bytes = storage.get_bytes(raw_key)
    pdf = pdfium.PdfDocument(raw_bytes)
    page_count = len(pdf)

    # 144 DPI keeps individual cells readable for OCR while staying under
    # ~1.5 MB per JPEG for a Letter-sized page. The scale factor also bridges
    # MinerU's PDF-point bbox coordinates and the rendered pixel coordinates
    # (bbox_px = bbox_pt * scale).
    _RENDER_SCALE = 144 / 72

    def render(page_idx: int, bbox: list[float] | tuple[float, ...] | None = None) -> bytes:
        """Render ``page_idx`` to JPEG.

        When ``bbox`` is provided (MinerU PDF-point coordinates
        ``[x0, y0, x1, y1]``), the result is cropped to that region. This
        is critical for cross-page table rescue: rendering the full page
        feeds the VLM headings / paragraphs / footnotes located outside
        the table, which the model then mis-packs into table rows
        (observed on sample 4abe6b71… p55: heading + paragraph + footnote
        leaked into the rescued policy table as padding rows).
        """
        if not (0 <= page_idx < page_count):
            return b""
        page = pdf[page_idx]
        pil_image = page.render(scale=_RENDER_SCALE).to_pil()
        if bbox is not None and len(bbox) >= 4:
            try:
                x0, y0, x1, y1 = (float(v) * _RENDER_SCALE for v in bbox[:4])
            except (TypeError, ValueError):
                x0 = y0 = x1 = y1 = 0.0
            if x1 > x0 and y1 > y0:
                w, h = pil_image.size
                # Clamp to image bounds; PIL .crop is forgiving but clamping
                # keeps the resulting JPEG smaller and avoids confusing
                # downstream VLM with empty margins.
                x0 = max(0.0, min(float(w), x0))
                y0 = max(0.0, min(float(h), y0))
                x1 = max(0.0, min(float(w), x1))
                y1 = max(0.0, min(float(h), y1))
                if x1 > x0 and y1 > y0:
                    pil_image = pil_image.crop((int(x0), int(y0), int(x1), int(y1)))
        from io import BytesIO
        buf = BytesIO()
        pil_image.save(buf, format="JPEG", quality=85)
        return buf.getvalue()

    return render


def _build_normalized_document(
    raw_object: models.RawObject,
    artifact: models.ParseArtifact,
    parse_payload: dict[str, Any],
    ctx: PipelineContext,
) -> dict[str, Any]:
    image_uris: dict[str, str] = artifact.metadata_summary.get("image_uris", {})

    pdf_info = parse_payload.get("pdf_info")
    toc: list[dict] = []
    if isinstance(pdf_info, list) and pdf_info:
        pdf_renderer = _make_pdf_renderer(raw_object, ctx.storage)
        blocks, body_markdown, toc = mineru_converter.convert(
            pdf_info,
            image_uris,
            ctx.image_analyzer,
            ctx.storage,
            pdf_renderer=pdf_renderer,
        )
    else:
        # Fallback: fake adapter or legacy format with top-level 'markdown'/'blocks'
        raw_md = parse_payload.get("markdown") or parse_payload.get("content") or ""
        # Native Office output commonly provides markdown rather than PDF's
        # ``pdf_info``. Do not truncate it here: this is the source used for
        # governance and chunking, and NormalizeService already applies its
        # own bounded input policy for LLM calls.
        body_markdown = str(raw_md)
        raw_blocks = parse_payload.get("blocks")
        blocks = raw_blocks if isinstance(raw_blocks, list) else [{
            "block_id": "block-001",
            "block_type": "paragraph",
            "seq_no": 1,
            "text": body_markdown[:4000],
            "source_locator": {},
        }]
        raw_sections = parse_payload.get("sections")
        if isinstance(raw_sections, list):
            toc = [
                {
                    "section_id": section.get("section_id"),
                    "title": section.get("heading"),
                    "level": section.get("level"),
                    "md_char_range": section.get("md_char_range"),
                    "start_block_id": section.get("start_block_id"),
                    "end_block_id": section.get("end_block_id"),
                }
                for section in raw_sections
                if isinstance(section, dict) and section.get("heading")
            ]

    # Slice 0+1: extract document-level metadata (title / authors / publish_date
    # / keywords / abstract / outline) so it lives ONCE on the ref and never
    # gets duplicated into per-chunk metadata downstream. Contributing blocks
    # are stamped with role=document_metadata so the semantic-repack layer
    # (slice 2) skips them as RAG chunk candidates.
    from nexus_app.normalize.document_metadata_extractor import extract as _extract_doc_md

    doc_metadata, contributed_ids = _extract_doc_md(blocks, body_markdown, toc)
    if contributed_ids:
        for b in blocks:
            if b.get("block_id") in contributed_ids:
                meta = dict(b.get("metadata") or {})
                meta["role"] = "document_metadata"
                b["metadata"] = meta

    metadata = {
        "filename": raw_object.metadata_summary.get("filename"),
        "mime_type": raw_object.mime_type,
        "backend": artifact.metadata_summary.get("backend") or artifact.metadata_summary.get("model_version"),
        "ocr_enabled": artifact.metadata_summary.get("ocr_enabled", False),
    }
    recovery_summary = mineru_converter.talent_training_plan_structure_recovery_summary(blocks)
    if recovery_summary["table_count"]:
        metadata["talent_training_plan_structure_recovery"] = recovery_summary
    if parse_payload.get("parser_backend"):
        metadata["parser_backend"] = parse_payload.get("parser_backend")
    if parse_payload.get("sections"):
        metadata["sections"] = parse_payload.get("sections")
    if parse_payload.get("retrieval_hints"):
        metadata["retrieval_hints"] = parse_payload.get("retrieval_hints")
    if parse_payload.get("quality"):
        metadata["main_content_quality"] = parse_payload.get("quality")

    major_profile_payload: dict[str, Any] | None = None
    try:
        from nexus_app.major_profile.extractor import extract as _extract_major_profile
        from nexus_app.major_profile.schema import validate_payload as _validate_major_profile_payload
        major_profile_payload = _extract_major_profile({
            "content_type": "document",
            "title": title_from(raw_object, parse_payload),
            "blocks": blocks,
            "body_markdown": body_markdown,
        })
        if major_profile_payload is not None:
            major_profile_payload = _validate_major_profile_payload(major_profile_payload)
    except Exception:
        logger.warning("major_profile extraction failed during normalize", exc_info=True)
        major_profile_payload = None
    major_profile_quality_summary: dict[str, Any] | None = None
    if major_profile_payload is not None:
        from nexus_app.major_profile.schema import (
            aggregate_quality_flags as _aggregate_major_profile_quality_flags,
            blocking_reasons_from_flags as _major_profile_blocking_reasons,
        )

        raw_major_profiles = major_profile_payload.get("profiles")
        major_profile_summaries = [
            profile
            for profile in (
                raw_major_profiles
                if isinstance(raw_major_profiles, list)
                else [major_profile_payload]
            )
            if isinstance(profile, dict)
        ]
        major_profile_quality_flags = _aggregate_major_profile_quality_flags(
            major_profile_summaries
        )
        major_profile_blocking_reasons = _major_profile_blocking_reasons(
            major_profile_quality_flags
        )
        major_profile_quality_summary = {
            "schema_version": "major_profile_quality.v1",
            "profile_count": len(major_profile_summaries),
            "quality_flags": major_profile_quality_flags,
            "blocking_reasons": major_profile_blocking_reasons,
            "validation_status": (
                "review_required" if major_profile_blocking_reasons else "pass"
            ),
        }
        metadata["domain_profile"] = "major_profile.v1"
        metadata["domain_profiles"] = [
            {
                "domain": "major",
                "domain_profile": "major_profile.v1",
                "extractor": profile.get("extractor_version"),
                "confidence": profile.get("confidence"),
                "major_code": profile.get("major_code"),
                "major_name": profile.get("major_name"),
                "education_level": profile.get("education_level"),
                "evidence_block_ids": (
                    profile.get("evidence", {}).get("source_block_ids")
                    if isinstance(profile.get("evidence"), dict)
                    else []
                ),
                "quality_flags": (
                    profile.get("quality_flags")
                    if isinstance(profile.get("quality_flags"), dict)
                    else {}
                ),
                "domain_table_status": "pending",
            }
            for profile in major_profile_summaries
        ]
        metadata["major_profile_count"] = len(major_profile_summaries)
        metadata["major_profile_quality"] = major_profile_quality_summary
        metadata["knowledge_emissions"] = [{
            "code": "major_profile_knowledge",
            "name": "专业介绍知识",
            "primary": True,
            "confidence": major_profile_payload.get("confidence", 0.85),
            "source": "profile_detect",
            "evidence": ["major_profile.v1 section signatures detected"],
            "co_emission_origin": None,
        }]

    talent_training_plan_payload: dict[str, Any] | None = None
    try:
        from nexus_app.talent_training_plan.extractor import extract as _extract_talent_training_plan

        talent_training_plan_payload = _extract_talent_training_plan({
            "content_type": "document",
            "title": title_from(raw_object, parse_payload),
            "blocks": blocks,
            "body_markdown": body_markdown,
        })
    except Exception:
        logger.warning("talent_training_plan extraction failed during normalize", exc_info=True)
    if talent_training_plan_payload is not None:
        metadata["talent_training_plan"] = {
            "domain_profile": "talent_training_plan.v1",
            "extractor": talent_training_plan_payload.get("extractor_version"),
            "confidence": talent_training_plan_payload.get("confidence"),
            "institution_name": talent_training_plan_payload.get("institution_name"),
            "major_code": talent_training_plan_payload.get("major_code"),
            "major_name": talent_training_plan_payload.get("major_name"),
            "course_count": len(talent_training_plan_payload.get("courses") or []),
            "domain_table_status": "pending",
        }

    teaching_standard_payload: dict[str, Any] | None = None
    teaching_standard_extraction: dict[str, Any] | None = None
    course_standard_payload: dict[str, Any] | None = None
    course_standard_extraction: dict[str, Any] | None = None
    try:
        from nexus_app.teaching_standard import extract_with_diagnostics as _extract_teaching_standard
        rule_result = _extract_teaching_standard({
            "content_type": "document",
            "title": title_from(raw_object, parse_payload),
            "blocks": blocks,
            "toc": toc,
        })
        teaching_standard_payload = rule_result.payload
        if teaching_standard_payload is None:
            from nexus_app.teaching_standard.course_standard import (
                extract_with_diagnostics as _extract_course_standard,
            )

            course_standard_result = _extract_course_standard({
                "content_type": "document",
                "title": title_from(raw_object, parse_payload),
                "blocks": blocks,
                "toc": toc,
            })
            course_standard_payload = course_standard_result.payload
            course_standard_extraction = (
                course_standard_payload.get("extractor")
                if course_standard_payload is not None
                else {
                    "strategy": "rule",
                    "version": "course_standard_table_extractor.v1",
                    "status": "not_adopted",
                    "reason": course_standard_result.failure_reason,
                }
            )

        if teaching_standard_payload is None and course_standard_payload is None:
            # The fallback receives the same normalized blocks, never the raw
            # file or MinerU result. It is intentionally opt-in via the
            # extraction alias and cannot write staging data directly.
            from nexus_app.teaching_standard.llm_fallback import extract as _llm_fallback
            fallback = _llm_fallback(
                {"content_type": "document", "title": title_from(raw_object, parse_payload), "blocks": blocks, "toc": toc},
                llm_client=ctx.teaching_standard_llm_client,
                model_alias=ctx.settings.litellm_extraction_model_alias,
                rule_failure_reason=rule_result.failure_reason or "rule_extraction_failed",
            )
            teaching_standard_payload = fallback.payload
            teaching_standard_extraction = fallback.metadata
        else:
            teaching_standard_extraction = teaching_standard_payload.get("extractor")
    except Exception:
        logger.warning("teaching_standard table extraction failed during normalize", exc_info=True)
    if teaching_standard_payload is not None:
        metadata["teaching_standard_graph_rows"] = len(teaching_standard_payload["rows"])
        metadata["domain_profile"] = "teaching_standard.v1"
    if teaching_standard_extraction is not None:
        metadata["teaching_standard_extraction"] = teaching_standard_extraction
    if course_standard_payload is not None:
        metadata["course_standard_graph_rows"] = len(course_standard_payload["rows"])
        metadata["domain_profile"] = "course_standard.v1"
    if course_standard_extraction is not None:
        metadata["course_standard_extraction"] = course_standard_extraction

    office_quality = _office_parse_quality(
        raw_object.mime_type,
        parse_payload,
        blocks,
        body_markdown,
        image_uris,
    )
    anomaly_items = list(
        major_profile_quality_summary.get("blocking_reasons", [])
        if major_profile_quality_summary else []
    )
    anomaly_items.extend(office_quality["anomaly_items"])

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
        "toc": toc,
        "document_metadata": doc_metadata,
        "blocks": blocks,
        "body_markdown": body_markdown,
        "attachments": _extract_attachments(artifact),
        "metadata": metadata,
        **({"major_profile": major_profile_payload} if major_profile_payload else {}),
        **({"talent_training_plan": talent_training_plan_payload} if talent_training_plan_payload else {}),
        **({"teaching_standard": teaching_standard_payload} if teaching_standard_payload else {}),
        **({"course_standard": course_standard_payload} if course_standard_payload else {}),
        "governance": {
            "sensitivity_level": None,
            "org_scope": [],
            "version_status": "processing",
        },
        "quality": {
            "parse_score": None,
            "normalize_score": None,
            "anomaly_items": anomaly_items,
            "manual_review_status": (
                "required"
                if (
                    major_profile_quality_summary
                    and major_profile_quality_summary.get("blocking_reasons")
                ) or office_quality["manual_review_required"]
                else "not_required"
            ),
            **({"office_parse": office_quality} if office_quality["is_office"] else {}),
            **(
                {"major_profile": major_profile_quality_summary}
                if major_profile_quality_summary else {}
            ),
        },
        "lineage": {
            "raw_object_id": raw_object.id,
            "raw_object_uri": raw_object.object_uri,
            "parse_artifact_id": artifact.id,
            "parse_artifact_uri": artifact.artifact_uri,
            "image_uris": image_uris,
        },
    }


_OFFICE_DOCUMENT_MIME_TYPES = frozenset({
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
})


def _office_parse_quality(
    mime_type: str | None,
    parse_payload: dict[str, Any],
    blocks: list[dict[str, Any]],
    body_markdown: str,
    image_uris: dict[str, str],
) -> dict[str, Any]:
    """Summarize native DOCX/PPTX output without interpreting raw Office data.

    The result is normalized-document quality evidence only. Existing
    governance rules retain ownership of official state decisions.
    """
    normalized_mime = (mime_type or "").lower()
    is_office = normalized_mime in _OFFICE_DOCUMENT_MIME_TYPES
    if not is_office:
        return {
            "is_office": False,
            "anomaly_items": [],
            "manual_review_required": False,
        }

    text_blocks = sum(
        1
        for block in blocks
        if isinstance(block, dict)
        and isinstance(block.get("text") or block.get("content"), str)
        and (block.get("text") or block.get("content")).strip()
    )
    table_blocks = sum(
        1 for block in blocks if isinstance(block, dict) and block.get("block_type") == "table"
    )
    title_blocks = sum(
        1 for block in blocks if isinstance(block, dict) and block.get("block_type") == "title"
    )
    markdown_char_count = len(body_markdown.strip())
    anomaly_items: list[str] = []
    if not blocks or not markdown_char_count:
        anomaly_items.append("office_parse_empty_content")
    elif not text_blocks and image_uris:
        anomaly_items.append("office_parse_image_only")
    elif len(blocks) == 1 and markdown_char_count > 20_000:
        anomaly_items.append("office_parse_single_block_degraded")

    return {
        "is_office": True,
        "source_format": "docx" if "wordprocessingml" in normalized_mime else "pptx",
        "output_shape": {
            "has_pdf_info": isinstance(parse_payload.get("pdf_info"), list),
            "has_markdown": isinstance(parse_payload.get("markdown"), str),
            "has_blocks": isinstance(parse_payload.get("blocks"), list),
        },
        "block_count": len(blocks),
        "text_block_count": text_blocks,
        "title_block_count": title_blocks,
        "table_block_count": table_blocks,
        "image_count": len(image_uris),
        "markdown_char_count": markdown_char_count,
        "anomaly_items": anomaly_items,
        "manual_review_required": bool(anomaly_items),
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
    *,
    profile_dict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # When profile_detect has run (Pipeline B B2.3), prefer its record_type +
    # domain_profile over the raw_object metadata fallback so downstream
    # consumers (B7 governance, B9 console) read the canonical detected value.
    # The raw_object.metadata_summary["record_type"] path stays as the legacy
    # fallback for JSON ingestion which doesn't run profile_detect.
    if profile_dict:
        record_type = profile_dict.get("record_type") or raw_object.metadata_summary.get(
            "record_type", "generic"
        )
    else:
        record_type = raw_object.metadata_summary.get("record_type", "generic")

    # Top-level domain_profile mirrors profile.domain_profile so downstream
    # (B4 / B6 / B7 / B9) can route on it without parsing the full profile
    # dict. JSON-path ingestion (no profile_detect) gets None here.
    domain_profile = profile_dict.get("domain_profile") if profile_dict else None

    # B3.5: project ParsedWorkbook → contract-shape record_body so the B4/B6
    # writers don't have to re-derive {dataset, records} / {analysis, tasks}
    # at the writer layer. Legacy JSON ingestion (no profile_dict) passes
    # through unchanged.
    record_body = project_to_record_body(raw_payload, profile_dict)

    payload: dict[str, Any] = {
        "schema_version": NORMALIZED_RECORD_SCHEMA_VERSION,
        "asset_id": None,
        "version_id": None,
        "source_type": raw_object.source_type.value,
        "record_type": record_type,
        "domain_profile": domain_profile,
        "record_key": raw_object.source_uri or raw_object.id,
        "title": title_from(raw_object, raw_payload),
        "language": "zh-CN",
        "record_body": record_body,
        # body_markdown + body_markdown_meta are contract-freeze §5.0
        # placeholders that B5 will populate with the LLM-rendered derivative
        # view. Carrying them as nulls now lets B5 / B7 / B9 read the v2
        # payload uniformly without having to special-case "missing field".
        "body_markdown": None,
        "body_markdown_meta": None,
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

    if profile_dict:
        # Top-level `profile` field is the contract-freeze §5.0 location and
        # the canonical read for B7 governance / B9 console.
        payload["profile"] = profile_dict
        # Mirror into `metadata` so it surfaces on
        # NormalizedAssetRef.metadata_summary["profile"] / ["domain_profile"]
        # without a MinIO round-trip — search / list-views can filter
        # directly on the PG row.
        payload["metadata"]["profile"] = profile_dict
        payload["metadata"]["domain_profile"] = domain_profile

    return payload


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

    # B3: persist the same schema_version on the PG row that the MinIO
    # payload carries. Document (Pipeline A) stays on the legacy "schema-v1"
    # string; record (Pipeline B) tracks the v2 payload bump. A future B6 /
    # B7 migration can renormalise the document side; for now keeping it
    # untouched avoids disturbing the document chain at all.
    payload_schema_version = normalized_payload.get(
        "schema_version",
        NORMALIZED_RECORD_SCHEMA_VERSION
        if normalized_type == NormalizedType.RECORD
        else NORMALIZED_DOCUMENT_SCHEMA_VERSION,
    )
    ref = models.NormalizedAssetRef(
        version_id=version.id,
        normalized_type=normalized_type,
        object_uri="pending",
        schema_version=payload_schema_version,
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
        document_metadata=normalized_payload.get("document_metadata"),
    )
    ctx.session.add(ref)
    ctx.session.flush()

    # `ref.id` is the durable idempotency anchor for the object key. Commit it
    # before talking to object storage: an S3/MinIO retry must not retain the
    # worker job lock or any version-state writes.
    ref_id = ref.id
    version_id = version.id
    storage_key = normalized_key(
        ctx.settings, normalized_type, version_id, ref_id, checksum
    )
    ctx.session.commit()

    try:
        stored = ctx.storage.put_bytes(
            storage_key,
            content,
            "application/json",
            {"nexus-version-id": version_id, "nexus-ref-id": ref_id},
        )
    except Exception:
        # A committed anchor with no object must not be selected by the
        # generated-ref idempotency query on retry.
        failed_ref = ctx.session.get(models.NormalizedAssetRef, ref_id)
        if failed_ref is not None:
            failed_ref.status = NormalizedAssetRefStatus.FAILED
            ctx.session.commit()
        raise
    ref = ctx.session.get(models.NormalizedAssetRef, ref_id)
    version = ctx.session.get(models.AssetVersion, version_id)
    if ref is None or version is None:
        raise RuntimeError(f"normalized persistence anchors disappeared ref={ref_id}")
    ref.object_uri = stored.object_uri
    ctx.session.flush()

    if normalized_type == NormalizedType.DOCUMENT:
        plan_payload = normalized_payload.get("talent_training_plan")
        if isinstance(plan_payload, dict):
            from nexus_app.talent_training_plan.writer import write as _write_talent_training_plan

            plan = _write_talent_training_plan(ctx.session, ref, plan_payload)
            if plan is not None:
                ref.metadata_summary = {
                    **dict(ref.metadata_summary or {}),
                    "talent_training_plan": {
                        **dict((ref.metadata_summary or {}).get("talent_training_plan") or {}),
                        "domain_table_status": "generated",
                        "plan_id": plan.id,
                    },
                }

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
        {
            "normalized_ref_id": ref.id,
            "normalized_uri": ref.object_uri,
            # This contains strategy/alias/hash/outcome only; the normalized
            # table text itself remains in object storage and is never copied
            # into a job-stage audit record.
            **(
                {"teaching_standard_extraction": normalized_payload["metadata"]["teaching_standard_extraction"]}
                if isinstance(normalized_payload.get("metadata"), dict)
                and isinstance(normalized_payload["metadata"].get("teaching_standard_extraction"), dict)
                else {}
            ),
        },
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

    # The profile detector runs on normalized document structure before AI
    # governance. Do not let an incidental, low-quality profile detection
    # activate the Console's professional-profile presentation once the
    # official classification says this is another document domain.
    from nexus_app.major_profile.presentation import reconcile_presentation

    suppressed_projection = reconcile_presentation(normalized_ref, result.classification)
    if suppressed_projection is not None:
        write_audit(
            ctx.session,
            AuditEventType.DOMAIN_NORMALIZE_COMPLETED,
            "normalized_asset_ref",
            normalized_ref.id,
            ctx.trace_id,
            {
                "action": "presentation_projection_suppressed",
                "governance_result_id": result.id,
                **suppressed_projection,
            },
        )

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
# Knowledge Chunking — Pipeline 5a: internal chunks for governed assets
# ---------------------------------------------------------------------------

def _audit_chunking_skipped(
    ctx: PipelineContext,
    normalized_ref: models.NormalizedAssetRef,
    reason: str,
    extra: dict | None = None,
) -> None:
    """Persist a KNOWLEDGE_CHUNKING_SKIPPED audit event so operators can see
    why an asset that passed governance never reached the knowledge base
    (§13). Idempotent-skip cases (chunks already exist) are NOT audited —
    they're a normal retry path, not a real skip."""
    summary: dict = {
        "normalized_ref_id": normalized_ref.id,
        "version_id": normalized_ref.version_id,
        "reason": reason,
    }
    if extra:
        summary.update(extra)
    write_audit(
        ctx.session,
        AuditEventType.KNOWLEDGE_CHUNKING_SKIPPED,
        target_type="normalized_asset_ref",
        target_id=normalized_ref.id,
        trace_id=ctx.trace_id,
        summary=summary,
    )


def _knowledge_chunking_gate(
    ctx: PipelineContext,
    version: models.AssetVersion,
    normalized_ref: models.NormalizedAssetRef,
) -> tuple[bool, dict[str, Any]]:
    """Return whether Nexus-owned chunk construction may run for this ref.

    External indexing still requires ``version_status=available`` in
    ``run_index_submit``. This gate is intentionally narrower: it lets Console
    previews and downstream internal KG work build source-traceable chunks when
    governance has admitted the normalized ref but the version remains
    ``review_required`` because the quality level is warning instead of pass.
    """
    if version.version_status == AssetVersionStatus.AVAILABLE:
        return True, {
            "chunking_admission": "version_available",
            "version_status": version.version_status.value,
        }

    if version.version_status != AssetVersionStatus.REVIEW_REQUIRED:
        return False, {
            "reason": f"version not available (status={version.version_status.value})",
            "version_status": version.version_status.value,
        }

    latest_result = ctx.session.scalars(
        select(models.GovernanceResult)
        .where(models.GovernanceResult.normalized_ref_id == normalized_ref.id)
        .order_by(models.GovernanceResult.created_at.desc())
        .limit(1)
    ).first()
    if latest_result is None:
        return False, {
            "reason": "version review_required without governance_result",
            "version_status": version.version_status.value,
        }
    if latest_result.status != GovernanceResultStatus.AVAILABLE:
        return False, {
            "reason": (
                "version review_required and latest governance_result "
                f"status={latest_result.status.value}"
            ),
            "version_status": version.version_status.value,
            "governance_result_id": latest_result.id,
            "governance_result_status": latest_result.status.value,
        }
    if not latest_result.index_admission:
        return False, {
            "reason": "version review_required and latest governance_result not index-admitted",
            "version_status": version.version_status.value,
            "governance_result_id": latest_result.id,
            "governance_result_status": latest_result.status.value,
            "index_admission": latest_result.index_admission,
        }

    quality_summary = latest_result.quality_summary or {}
    blocking_reasons = quality_summary.get("blocking_reasons") or []
    if blocking_reasons:
        return False, {
            "reason": "version review_required with blocking quality reasons",
            "version_status": version.version_status.value,
            "governance_result_id": latest_result.id,
            "governance_result_status": latest_result.status.value,
            "index_admission": latest_result.index_admission,
            "blocking_reasons": list(blocking_reasons),
        }

    non_auto_fields = [
        entry.get("field_name")
        for entry in (latest_result.decision_trail or [])
        if entry.get("adoption_status") != "auto_adopted"
    ]
    if non_auto_fields:
        return False, {
            "reason": "version review_required with non-auto-adopted governance fields",
            "version_status": version.version_status.value,
            "governance_result_id": latest_result.id,
            "governance_result_status": latest_result.status.value,
            "index_admission": latest_result.index_admission,
            "non_auto_fields": non_auto_fields,
        }

    return True, {
        "chunking_admission": "governance_index_admitted",
        "version_status": version.version_status.value,
        "governance_result_id": latest_result.id,
        "governance_result_status": latest_result.status.value,
        "index_admission": latest_result.index_admission,
        "quality_level": quality_summary.get("quality_level"),
        "quality_score": quality_summary.get("quality_score"),
    }


def _recover_knowledge_emissions(
    ctx: PipelineContext,
    normalized_ref: models.NormalizedAssetRef,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Re-materialize deterministic emissions from the latest official result.

    A historical worker could reach chunking before a governance write became
    durable.  Retrying that job must not leave an index-admitted ref permanently
    unsearchable merely because its original stage recorded a skip.
    """
    from nexus_app.ai_governance.knowledge_type_inference import (
        infer_knowledge_emissions_for_classification,
    )
    from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry
    from nexus_app.ai_governance.services import AIGovernanceService

    # Recovery can be invoked by retry and maintenance entry points where the
    # caller's ORM object belongs to a different Session. Keep only its stable
    # id; all reads and writes below must use ctx.session's identity map.
    normalized_ref_id = normalized_ref.id
    latest_result = ctx.session.scalars(
        select(models.GovernanceResult)
        .where(models.GovernanceResult.normalized_ref_id == normalized_ref_id)
        .order_by(models.GovernanceResult.created_at.desc())
        .limit(1)
    ).first()
    ai_run = ctx.session.scalars(
        select(models.AIGovernanceRun)
        .where(
            models.AIGovernanceRun.normalized_ref_id == normalized_ref_id,
            models.AIGovernanceRun.validation_status
            == AIGovernanceRunValidationStatus.SCHEMA_VALID,
            models.AIGovernanceRun.ai_output.is_not(None),
        )
        .order_by(models.AIGovernanceRun.created_at.desc())
        .limit(1)
    ).first()
    if latest_result is None and ai_run is None:
        return [], {
            "recovery": "unavailable",
            "reason": "no schema-valid AI governance run",
        }

    registry = GovernanceRulesRegistry()
    try:
        registry.load(ctx.session)
        if latest_result is not None and latest_result.classification:
            emissions = infer_knowledge_emissions_for_classification(
                latest_result.classification, registry, confidence=1.0
            )
            ref = ctx.session.get(models.NormalizedAssetRef, normalized_ref_id)
            if ref is not None:
                summary = dict(ref.metadata_summary or {})
                summary["knowledge_emissions"] = emissions
                ref.metadata_summary = summary
                ctx.session.flush()
        elif ai_run is not None:
            emissions = AIGovernanceService().write_knowledge_emissions(
                ctx.session, ai_run, registry
            )
        else:
            emissions = []
    except Exception as exc:
        logger.warning(
            "Unable to recover knowledge emissions for ref %s: %s",
            normalized_ref_id,
            exc,
        )
        return [], {
            "recovery": "failed",
            "ai_run_id": ai_run.id if ai_run is not None else None,
            "reason": f"{type(exc).__name__}: {exc}"[:500],
        }

    # Do not refresh the caller-provided instance: it can be detached after a
    # prior transaction/session boundary, which raises InvalidRequestError.
    # The emission writer has already flushed the canonical row in ctx.session.
    if ctx.session.get(models.NormalizedAssetRef, normalized_ref_id) is None:
        raise RuntimeError(
            "normalized ref disappeared during knowledge-emission recovery: "
            f"{normalized_ref_id}"
        )
    return emissions, {
        "recovery": "materialized" if emissions else "no_applicable_emission",
        "ai_run_id": ai_run.id if ai_run is not None else None,
        "governance_result_id": latest_result.id if latest_result is not None else None,
        "emission_count": len(emissions),
    }


def _invalid_knowledge_emission_codes(emissions: object) -> list[str]:
    """Return invalid persisted codes so old projections are re-materialized."""
    if not isinstance(emissions, list):
        return ["<malformed>"]
    from nexus_app.knowledge.config_loader import get_all_knowledge_type_configs

    valid_codes = set(get_all_knowledge_type_configs())
    invalid: list[str] = []
    for emission in emissions:
        code = emission.get("code") if isinstance(emission, dict) else None
        if not isinstance(code, str) or code not in valid_codes:
            invalid.append(str(code) if code is not None else "<missing>")
    return list(dict.fromkeys(invalid))


def _enqueue_evidence_graph_build_if_requested(
    ctx: PipelineContext,
    normalized_ref: models.NormalizedAssetRef,
    emissions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Queue, but never execute, a graph build requested by the primary emission."""
    graph_profiles = {
        emission.get("graph_profile")
        for emission in emissions
        if isinstance(emission, dict) and isinstance(emission.get("graph_profile"), str)
    }
    if not graph_profiles:
        return None

    from nexus_app.evidence_graph import (
        KnowledgeGraphBuildStatus,
        create_graph_build,
        get_existing_graph_build,
        select_graph_candidate_chunks,
    )

    graph_profile = sorted(graph_profiles)[0]
    strategy_version = "evidence_kg.v1"
    selection = select_graph_candidate_chunks(
        ctx.session,
        normalized_ref_id=normalized_ref.id,
        graph_profile=graph_profile,
    )
    if selection.selected_chunk_count == 0:
        return {
            "status": "skipped",
            "reason": "no graph candidate chunks",
            "graph_profile": graph_profile,
            "candidate_count": 0,
        }

    existing = get_existing_graph_build(
        ctx.session,
        normalized_ref_id=normalized_ref.id,
        graph_profile=graph_profile,
        strategy_version=strategy_version,
    )
    if existing is not None:
        return {
            "status": "existing",
            "build_id": existing.id,
            "graph_profile": graph_profile,
            "candidate_count": selection.selected_chunk_count,
        }

    # A terminal zero-row build is intentionally not reusable, but the active
    # build-key uniqueness constraint still requires it to be retired before
    # this recovered pipeline can enqueue a fresh attempt.
    nonreusable_builds = list(ctx.session.scalars(
        select(models.KnowledgeGraphBuild).where(
            models.KnowledgeGraphBuild.normalized_ref_id == normalized_ref.id,
            models.KnowledgeGraphBuild.graph_type == "evidence_grounded_kg",
            models.KnowledgeGraphBuild.graph_profile == graph_profile,
            models.KnowledgeGraphBuild.strategy_version == strategy_version,
            models.KnowledgeGraphBuild.status
            != KnowledgeGraphBuildStatus.DEPRECATED,
        )
    ))
    for nonreusable_build in nonreusable_builds:
        nonreusable_build.status = KnowledgeGraphBuildStatus.DEPRECATED
    if nonreusable_builds:
        ctx.session.flush()

    build = create_graph_build(
        ctx.session,
        normalized_ref_id=normalized_ref.id,
        graph_profile=graph_profile,
        strategy_version=strategy_version,
        source_chunk_count=selection.total_semantic_chunk_count,
        candidate_count=selection.selected_chunk_count,
        status=KnowledgeGraphBuildStatus.PENDING,
        quality_summary={
            "candidate_selection": {
                "selected_chunk_count": selection.selected_chunk_count,
                "skipped_chunk_count": selection.skipped_chunk_count,
                "by_anchor_role": selection.by_anchor_role,
                "skipped_by_reason": selection.skipped_by_reason,
            },
            "pipeline_submit": "primary_knowledge_emission_graph_profile",
        },
    )
    return {
        "status": "queued",
        "build_id": build.id,
        "graph_profile": graph_profile,
        "candidate_count": selection.selected_chunk_count,
    }


def run_knowledge_chunking(
    ctx: PipelineContext,
    version: models.AssetVersion,
    normalized_ref: models.NormalizedAssetRef,
) -> list[models.KnowledgeChunk]:
    """Stage 5a: Generate KnowledgeChunk records via Knowledge Pipeline.

    Skipped when:
    - version is neither available nor governed/index-admitted review_required
    - normalized_ref.metadata_summary.knowledge_emissions is missing/empty
    """
    started_at = _stage_started()
    admitted, admission_detail = _knowledge_chunking_gate(ctx, version, normalized_ref)
    if not admitted:
        reason = admission_detail.get(
            "reason",
            f"version not available (status={version.version_status.value})",
        )
        _add_stage(ctx, "knowledge_chunking", StageStatus.SKIPPED,
                   admission_detail, started_at=started_at)
        _audit_chunking_skipped(ctx, normalized_ref, reason,
                                admission_detail)
        return []

    emissions = (normalized_ref.metadata_summary or {}).get("knowledge_emissions", [])
    invalid_codes = _invalid_knowledge_emission_codes(emissions)
    if not emissions or invalid_codes:
        emissions, recovery_detail = _recover_knowledge_emissions(ctx, normalized_ref)
        if invalid_codes:
            recovery_detail["replaced_invalid_codes"] = invalid_codes
    else:
        recovery_detail = {"recovery": "not_needed"}
    if not emissions:
        reason = "no knowledge_emissions on normalized_ref"
        _add_stage(ctx, "knowledge_chunking", StageStatus.SKIPPED,
                   {"reason": reason, **recovery_detail}, started_at=started_at)
        _audit_chunking_skipped(ctx, normalized_ref, reason, recovery_detail)
        return []

    # Idempotency: if chunks already exist for this ref (job retry), reuse them.
    existing = list(ctx.session.scalars(
        select(models.KnowledgeChunk).where(
            models.KnowledgeChunk.normalized_ref_id == normalized_ref.id
        )
    ).all())
    if existing:
        # Not audited: this is the retry idempotent path, not a real skip.
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
        graph_detail = _enqueue_evidence_graph_build_if_requested(
            ctx, normalized_ref, emissions
        )
        if graph_detail is not None:
            _add_stage(
                ctx,
                "evidence_graph_submit",
                (
                    StageStatus.SUCCEEDED
                    if graph_detail["status"] in {"queued", "existing"}
                    else StageStatus.SKIPPED
                ),
                graph_detail,
                started_at=started_at,
            )
        return existing

    from nexus_app.knowledge.services import run_knowledge_pipeline

    # The normalized payload is in object storage. Release governance/chunk
    # admission reads before fetching it so a slow S3/MinIO response cannot
    # retain the worker transaction.
    ctx.session.commit()
    content, content_blocks, record_body, domain_payloads = _load_normalized_payload(
        ctx, normalized_ref
    )
    if domain_payloads.get("major_profile"):
        emissions = [
            {
                **emission,
                **(
                    {"major_profile": domain_payloads["major_profile"]}
                    if emission.get("code") == "major_profile_knowledge"
                    else {}
                ),
            }
            for emission in emissions
        ]
    if domain_payloads.get("talent_training_plan"):
        emissions = [
            {
                **emission,
                **(
                    {"talent_training_plan": domain_payloads["talent_training_plan"]}
                    if emission.get("code") == "talent_training_dataset"
                    else {}
                ),
            }
            for emission in emissions
        ]
    chunks = run_knowledge_pipeline(
        content, emissions, normalized_ref.id,
        content_blocks=content_blocks,
        record_body=record_body,
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
            **recovery_detail,
            **admission_detail,
        },
        started_at=started_at,
    )
    graph_detail = _enqueue_evidence_graph_build_if_requested(
        ctx, normalized_ref, emissions
    )
    if graph_detail is not None:
        _add_stage(
            ctx,
            "evidence_graph_submit",
            (
                StageStatus.SUCCEEDED
                if graph_detail["status"] in {"queued", "existing"}
                else StageStatus.SKIPPED
            ),
            graph_detail,
            started_at=started_at,
        )
    return chunks


def run_knowledge_outline_build(
    ctx: PipelineContext,
    version: models.AssetVersion,
    normalized_ref: models.NormalizedAssetRef,
    chunks: list[models.KnowledgeChunk],
) -> None:
    """Stage 5a.1: build textbook knowledge outline before index submit.

    This stage is intentionally best-effort for rollout safety: an outline
    failure is observable as a failed stage, but it does not block the
    established chunking -> index_submit path.
    """
    started_at = _stage_started()
    if normalized_ref.normalized_type != NormalizedType.DOCUMENT:
        normalized_type = normalized_ref.normalized_type
        _add_stage(
            ctx,
            "knowledge_outline_build",
            StageStatus.SKIPPED,
            {
                "reason": "normalized_ref is not document",
                "normalized_ref_id": normalized_ref.id,
                "normalized_type": (
                    normalized_type.value
                    if hasattr(normalized_type, "value")
                    else str(normalized_type)
                ),
            },
            started_at=started_at,
        )
        return

    if not chunks:
        _add_stage(
            ctx,
            "knowledge_outline_build",
            StageStatus.SKIPPED,
            {
                "reason": "no knowledge chunks",
                "normalized_ref_id": normalized_ref.id,
            },
            started_at=started_at,
        )
        return

    if not _has_course_textbook_chunks_or_emissions(normalized_ref, chunks):
        _add_stage(
            ctx,
            "knowledge_outline_build",
            StageStatus.SKIPPED,
            {
                "reason": "not course_textbook knowledge",
                "normalized_ref_id": normalized_ref.id,
            },
            started_at=started_at,
        )
        return

    existing_outline_count = ctx.session.scalar(
        select(func.count())
        .select_from(models.KnowledgeOutlineNode)
        .where(models.KnowledgeOutlineNode.normalized_ref_id == normalized_ref.id)
    ) or 0
    if existing_outline_count:
        _add_stage(
            ctx,
            "knowledge_outline_build",
            StageStatus.SKIPPED,
            {
                "reason": "knowledge outline already exists",
                "normalized_ref_id": normalized_ref.id,
                "outline_node_count": int(existing_outline_count),
            },
            started_at=started_at,
        )
        return

    try:
        from nexus_app.knowledge_outline.service import (
            KNOWLEDGE_OUTLINE_ELIGIBLE_SUBTYPES,
            build_and_persist_outline,
        )
        from nexus_app.task_outline.detector import detect_course_textbook_subtype
        from nexus_app.task_outline.schemas import TaskOutlineProfileCreate
        from nexus_app.task_outline.service import get_profile_by_ref, upsert_profile

        profile = get_profile_by_ref(
            ctx.session,
            normalized_ref_id=normalized_ref.id,
            asset_profile="course_textbook",
        )
        payload: dict[str, Any] | None = None
        detection: Any | None = None
        if profile is None:
            payload = _load_normalized_payload_dict(ctx, normalized_ref)
            blocks = (
                payload.get("blocks")
                if isinstance(payload.get("blocks"), list)
                else []
            )
            detection = detect_course_textbook_subtype(
                blocks,
                body_markdown=payload.get("body_markdown"),
            )
            textbook_subtype = detection.textbook_subtype
            subtype_confidence = detection.subtype_confidence
            processing_profile = detection.processing_profile
        else:
            textbook_subtype = profile.textbook_subtype
            subtype_confidence = (
                float(profile.subtype_confidence)
                if profile.subtype_confidence is not None
                else None
            )
            processing_profile = profile.processing_profile

        if textbook_subtype not in KNOWLEDGE_OUTLINE_ELIGIBLE_SUBTYPES:
            _add_stage(
                ctx,
                "knowledge_outline_build",
                StageStatus.SKIPPED,
                {
                    "reason": "textbook subtype is not knowledge-outline eligible",
                    "normalized_ref_id": normalized_ref.id,
                    "task_outline_profile_id": profile.id if profile else None,
                    "textbook_subtype": textbook_subtype,
                    "subtype_confidence": subtype_confidence,
                    "processing_profile": processing_profile,
                },
                started_at=started_at,
            )
            return

        if payload is None:
            payload = _load_normalized_payload_dict(ctx, normalized_ref)

        if profile is None and detection is not None:
            profile = upsert_profile(
                ctx.session,
                TaskOutlineProfileCreate(
                    normalized_ref_id=normalized_ref.id,
                    asset_version_id=version.id,
                    asset_profile="course_textbook",
                    title=payload.get("title") or normalized_ref.title,
                    textbook_subtype=detection.textbook_subtype,
                    task_profile=None,
                    subtype_confidence=Decimal(str(detection.subtype_confidence)),
                    processing_profile=detection.processing_profile,
                    evidence_graph_admission=detection.evidence_graph_admission,
                    source_block_ids=list(detection.source_block_ids),
                    quality={},
                    metadata={
                        "detector_scores": detection.scores,
                        "source": "pipeline.knowledge_outline_build",
                    },
                ),
            )

        tree = build_and_persist_outline(
            ctx.session,
            ref=normalized_ref,
            payload=payload,
            rules_etag=_try_governance_rules_etag(),
            trace_id=ctx.trace_id,
            actor_type="system",
            actor_id="pipeline.knowledge_outline_build",
            is_rebuild=False,
        )
        _add_stage(
            ctx,
            "knowledge_outline_build",
            StageStatus.SUCCEEDED,
            {
                "normalized_ref_id": normalized_ref.id,
                "task_outline_profile_id": profile.id if profile else None,
                "textbook_subtype": textbook_subtype,
                "subtype_confidence": subtype_confidence,
                "processing_profile": processing_profile,
                "outline": {
                    "build_run_id": tree.build_run_id,
                    "total_nodes": tree.total_nodes,
                    "max_depth": tree.max_depth,
                    "fallback_used": tree.fallback_used,
                },
            },
            started_at=started_at,
        )
    except Exception as exc:  # noqa: BLE001 - rollout-safe, non-blocking stage
        reason = f"{type(exc).__name__}: {exc}"
        logger.exception(
            "knowledge_outline_build failed for normalized_ref_id=%s",
            normalized_ref.id,
        )
        _add_stage(
            ctx,
            "knowledge_outline_build",
            StageStatus.FAILED,
            {
                "normalized_ref_id": normalized_ref.id,
                "non_blocking": True,
            },
            failure_reason=reason,
            started_at=started_at,
        )


def _has_course_textbook_chunks_or_emissions(
    normalized_ref: models.NormalizedAssetRef,
    chunks: list[models.KnowledgeChunk],
) -> bool:
    if any(chunk.knowledge_type_code == "course_textbook" for chunk in chunks):
        return True
    emissions = (normalized_ref.metadata_summary or {}).get("knowledge_emissions") or []
    return any(
        isinstance(emission, dict) and emission.get("code") == "course_textbook"
        for emission in emissions
    )


def _load_normalized_payload_dict(
    ctx: PipelineContext,
    normalized_ref: models.NormalizedAssetRef,
) -> dict[str, Any]:
    uri = normalized_ref.object_uri
    key = uri.split("/", 3)[-1] if uri.startswith("s3://") else uri
    raw = ctx.storage.get_bytes(key)
    return json.loads(raw.decode("utf-8"))


def _try_governance_rules_etag() -> str | None:
    try:
        from nexus_app.ai_governance.rules_registry import (
            get_governance_rules_registry,
        )

        return get_governance_rules_registry().get_rules_content_hash()
    except Exception:
        return None


def _load_normalized_content(
    ctx: PipelineContext,
    normalized_ref: models.NormalizedAssetRef,
) -> str:
    """Read just the textual content from normalized payload.

    Retained for callers that do not need block locators (e.g. AI governance
    input building). For knowledge chunking use _load_normalized_payload to
    receive blocks alongside content.
    """
    content, _, _, _ = _load_normalized_payload(ctx, normalized_ref)
    return content


def _load_normalized_payload(
    ctx: PipelineContext,
    normalized_ref: models.NormalizedAssetRef,
) -> tuple[
    str,
    list[dict[str, Any]] | None,
    dict[str, Any] | list[Any] | None,
    dict[str, Any],
]:
    """Read normalized payload and return ``(content, content_blocks, record_body)``.

    ``content`` is the canonical text passed into chunking strategies and
    LLM Prompt builders — byte-for-byte the value persisted in MinIO. Adding
    block-level locators here MUST NOT mutate ``content`` (see ARCHITECT
    "Chunk Locator Contract" and the md_char_range out-of-band rule).

    ``content_blocks`` is the ``normalized_document.blocks[]`` list when the
    payload describes a document; None for ``normalized_record`` payloads so
    record-type chunks correctly carry ``locator=None``.

    ``record_body`` is the parsed ``payload.record_body`` for record-pipeline
    refs (None for documents). Threaded through so row-oriented chunking
    strategies (``row_decompose``) can read the structured rows directly
    instead of re-parsing ``content`` — which, for record refs, may be the
    body_markdown rendering written by B5.3 rather than the JSON.
    """
    uri = normalized_ref.object_uri
    key = uri.split("/", 3)[-1] if uri.startswith("s3://") else uri
    raw = ctx.storage.get_bytes(key)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return raw.decode("utf-8", errors="ignore"), None, None, {}
    content = (
        payload.get("body_markdown")
        or json.dumps(payload.get("record_body", {}), ensure_ascii=False)
        or ""
    )
    record_body = payload.get("record_body")
    if not isinstance(record_body, (dict, list)):
        record_body = None
    blocks = payload.get("blocks")
    domain_payloads: dict[str, Any] = {}
    if isinstance(payload.get("major_profile"), dict):
        domain_payloads["major_profile"] = payload["major_profile"]
    if isinstance(payload.get("talent_training_plan"), dict):
        domain_payloads["talent_training_plan"] = payload["talent_training_plan"]
    if isinstance(blocks, list) and blocks:
        return content, blocks, record_body, domain_payloads
    return content, None, record_body, domain_payloads


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
        reason = f"version not available (status={version.version_status.value})"
        _add_stage(ctx, "index_submit", StageStatus.SKIPPED,
                   {"reason": reason}, started_at=started_at)
        write_audit(
            ctx.session,
            AuditEventType.INDEX_SUBMIT_SKIPPED,
            target_type="normalized_asset_ref",
            target_id=normalized_ref.id,
            trace_id=ctx.trace_id,
            summary={
                "normalized_ref_id": normalized_ref.id,
                "version_id": version.id,
                "reason": reason,
                "version_status": version.version_status.value,
            },
        )
        return []
    if not chunks:
        reason = "no knowledge chunks to index"
        _add_stage(ctx, "index_submit", StageStatus.SKIPPED,
                   {"reason": reason}, started_at=started_at)
        write_audit(
            ctx.session,
            AuditEventType.INDEX_SUBMIT_SKIPPED,
            target_type="normalized_asset_ref",
            target_id=normalized_ref.id,
            trace_id=ctx.trace_id,
            summary={
                "normalized_ref_id": normalized_ref.id,
                "version_id": version.id,
                "reason": reason,
            },
        )
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

    chunks_by_kt: dict[str, list[models.KnowledgeChunk]] = {}
    for chunk in chunks:
        chunks_by_kt.setdefault(chunk.knowledge_type_code, []).append(chunk)

    # NEXUS-owned chunks are indexed into pgvector. Only the legacy passthrough
    # descriptor path remains on the historical RAGFlow branch for compatibility.
    pgvector_chunks_by_kt: dict[str, list[models.KnowledgeChunk]] = {}
    ragflow_chunks_by_kt: dict[str, list[models.KnowledgeChunk]] = {}
    for kt_code, kt_chunks in chunks_by_kt.items():
        if all(c.chunk_type == ChunkType.PASSTHROUGH_DESCRIPTOR for c in kt_chunks):
            ragflow_chunks_by_kt[kt_code] = kt_chunks
            continue
        pgvector_chunks_by_kt[kt_code] = kt_chunks

    # Existing manifests/chunks were read above and are now represented by
    # plain ids and values. The following embedding/RAGFlow requests must not
    # retain that read transaction or prior stage writes.
    ctx.session.commit()

    manifests: list[models.IndexManifest] = []
    error_messages: list[str] = []
    pgvector_index_summaries: list[dict[str, Any]] = []

    if pgvector_chunks_by_kt:
        from nexus_app.index.pgvector_indexer import index_chunks_pgvector

        embedding_client = get_pgvector_embedding_client(ctx.settings)
        for kt_code, kt_chunks in pgvector_chunks_by_kt.items():
            if kt_code in existing_by_kt:
                manifests.append(existing_by_kt[kt_code])
                continue
            try:
                result = index_chunks_pgvector(
                    ctx.session,
                    normalized_ref,
                    kt_chunks,
                    settings=ctx.settings,
                    embedding_client=embedding_client,
                    trace_id=ctx.trace_id,
                )
                manifest = models.IndexManifest(
                    normalized_ref_id=normalized_ref.id,
                    knowledge_type_code=kt_code,
                    index_status=IndexManifestStatus.INDEXED,
                    chunk_count=result.embedded_chunk_count,
                    indexed_at=models.utcnow(),
                    trace_id=ctx.trace_id,
                )
                ctx.session.add(manifest)
                ctx.session.flush()
                manifests.append(manifest)
                pgvector_index_summaries.append({
                    "knowledge_type_code": kt_code,
                    "chunk_count": len(kt_chunks),
                    "embedded_chunk_count": result.embedded_chunk_count,
                    "collection_count": result.collection_count,
                    "collection_keys": result.collection_keys,
                })
            except Exception as exc:
                err = (
                    f"pgvector index_submit failed for kt={kt_code}: "
                    f"{type(exc).__name__}: {exc}"
                )
                logger.warning(err)
                error_messages.append(err)
                manifest = models.IndexManifest(
                    normalized_ref_id=normalized_ref.id,
                    knowledge_type_code=kt_code,
                    index_status=IndexManifestStatus.FAILED,
                    chunk_count=0,
                    error_message=err[:1000],
                    trace_id=ctx.trace_id,
                )
                ctx.session.add(manifest)
                ctx.session.flush()
                manifests.append(manifest)

    if ragflow_chunks_by_kt:
        from nexus_app.index.kb_registry import get_kb_registry
        from nexus_app.index.ragflow_adapter import get_ragflow_adapter
        from nexus_app.knowledge.config_loader import get_knowledge_type_config

    adapter = get_ragflow_adapter(ctx.settings) if ragflow_chunks_by_kt else None
    kb_registry = get_kb_registry() if ragflow_chunks_by_kt else None
    normalized_content = _load_normalized_content(ctx, normalized_ref) if ragflow_chunks_by_kt else ""
    doc_name_base = (normalized_ref.title or normalized_ref.id)[:120]

    for kt_code, kt_chunks in ragflow_chunks_by_kt.items():
        # A preceding knowledge type may have written a manifest. Publish it
        # before the next HTTP retry block, so every RAGFlow request starts
        # without an open worker transaction.
        ctx.session.commit()
        if kt_code in existing_by_kt:
            manifests.append(existing_by_kt[kt_code])
            continue
        try:
            kt_config = get_knowledge_type_config(kt_code)
            assert kb_registry is not None
            assert adapter is not None
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
                ragflow_kb_id=kb_registry.get_cached(kt_code) if kb_registry else None,
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
            "pgvector_knowledge_types": list(pgvector_chunks_by_kt.keys()),
            "ragflow_knowledge_types": list(ragflow_chunks_by_kt.keys()),
            "pgvector_index_summaries": pgvector_index_summaries,
            "manifest_count": len(manifests),
            "indexed_count": indexed_count,
            "failed_count": failed_count,
            "errors": error_messages,
        },
        failure_reason="; ".join(error_messages)[:1000] if error_messages else None,
        started_at=started_at,
    )
    return manifests
