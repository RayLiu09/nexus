"""Task Outline rebuild orchestration from normalized document payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.enums import IndexManifestStatus, NormalizedType
from nexus_app.task_outline.extractor import (
    TaskOutlineExtraction,
    extract_course_textbook_outline,
)
from nexus_app.task_outline.projector import (
    DEFAULT_KNOWLEDGE_TYPE_CODE,
    delete_projected_chunks,
    project_profile_to_chunks,
)
from nexus_app.task_outline.service import replace_nodes, upsert_profile
from nexus_app.task_outline.subtype_llm import (
    TextbookSubtypeArbiterProtocol,
    create_textbook_subtype_arbiter,
)


@dataclass(frozen=True)
class TaskOutlineRebuildResult:
    profile: models.TaskOutlineProfile
    nodes: list[models.TaskOutlineNode]
    chunks: list[models.KnowledgeChunk]
    quality: dict[str, Any]
    index_marked_stale: bool


def rebuild_task_outline_for_ref(
    session: Session,
    *,
    ref: models.NormalizedAssetRef,
    payload: dict[str, Any],
    knowledge_type_code: str = DEFAULT_KNOWLEDGE_TYPE_CODE,
    subtype_arbiter: TextbookSubtypeArbiterProtocol | None = None,
    use_default_subtype_arbiter: bool = True,
) -> TaskOutlineRebuildResult:
    """Rebuild Task Outline artifacts for one normalized document ref.

    The input is the persisted normalized payload, not raw file content or
    parser-specific output. Rebuild is idempotent: the effective profile is
    upserted, nodes are replaced, and prior Task Outline chunks are replaced or
    deleted depending on the detected textbook subtype.
    """
    if ref.normalized_type != NormalizedType.DOCUMENT:
        raise ValueError("task outline rebuild requires a normalized document")

    extraction = extract_course_textbook_outline(
        normalized_ref_id=ref.id,
        asset_version_id=ref.version_id,
        title=_title_for_ref(ref, payload),
        blocks=_blocks_from_payload(payload),
        body_markdown=_body_markdown_from_payload(payload),
        subtype_arbiter=(
            subtype_arbiter
            if subtype_arbiter is not None
            else create_textbook_subtype_arbiter()
            if use_default_subtype_arbiter
            else None
        ),
    )
    profile = upsert_profile(session, extraction.profile)
    nodes = replace_nodes(session, profile=profile, nodes=extraction.nodes)

    chunks: list[models.KnowledgeChunk] = []
    chunks_changed = False
    if _should_project_chunks(extraction):
        chunks = project_profile_to_chunks(
            session,
            profile=profile,
            knowledge_type_code=knowledge_type_code,
            replace_existing=True,
        )
        chunks_changed = True
    else:
        deleted_count = delete_projected_chunks(
            session,
            normalized_ref_id=profile.normalized_ref_id,
            profile_id=profile.id,
            knowledge_type_code=knowledge_type_code,
        )
        chunks_changed = deleted_count > 0

    index_marked_stale = False
    if chunks_changed:
        index_marked_stale = mark_index_manifest_stale(
            session,
            normalized_ref_id=ref.id,
            knowledge_type_code=knowledge_type_code,
        )

    session.flush()
    return TaskOutlineRebuildResult(
        profile=profile,
        nodes=nodes,
        chunks=chunks,
        quality=dict(extraction.quality),
        index_marked_stale=index_marked_stale,
    )


def mark_index_manifest_stale(
    session: Session,
    *,
    normalized_ref_id: str,
    knowledge_type_code: str = DEFAULT_KNOWLEDGE_TYPE_CODE,
) -> bool:
    """Mark an existing index manifest stale after derived chunk replacement."""
    manifest = session.scalar(
        select(models.IndexManifest).where(
            models.IndexManifest.normalized_ref_id == normalized_ref_id,
            models.IndexManifest.knowledge_type_code == knowledge_type_code,
        )
    )
    if manifest is None:
        return False
    manifest.index_status = IndexManifestStatus.STALE
    manifest.indexed_at = None
    manifest.error_message = None
    session.flush()
    return True


def _blocks_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = payload.get("blocks")
    if not isinstance(blocks, list):
        return []
    return [block for block in blocks if isinstance(block, dict)]


def _body_markdown_from_payload(payload: dict[str, Any]) -> str | None:
    body_markdown = payload.get("body_markdown")
    if isinstance(body_markdown, str) and body_markdown.strip():
        return body_markdown
    return None


def _title_for_ref(ref: models.NormalizedAssetRef, payload: dict[str, Any]) -> str | None:
    if ref.title:
        return ref.title
    title = payload.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        metadata_title = metadata.get("title")
        if isinstance(metadata_title, str) and metadata_title.strip():
            return metadata_title.strip()
    return None


def _should_project_chunks(extraction: TaskOutlineExtraction) -> bool:
    return (
        extraction.profile.textbook_subtype == "training_operation"
        and extraction.profile.task_profile == "textbook_training_operation"
        and bool(extraction.nodes)
    )
