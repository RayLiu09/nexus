"""Project Task Outline nodes into unified KnowledgeChunk rows."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.enums import ChunkingStrategy, ChunkType, EmbeddingStatus, SourceKind

DOMAIN_MODEL = "task_outline.v1"
SEMANTIC_VARIANT = "task_outline_repack"
DEFAULT_KNOWLEDGE_TYPE_CODE = "textbook_kb"

MUST_PROJECT_NODE_TYPES = {
    "task",
    "task_section",
    "operation_step",
    "task_artifact",
}
MAY_PROJECT_NODE_TYPES = {
    "project",
    "assessment",
}


def project_profile_to_chunks(
    session: Session,
    *,
    profile: models.TaskOutlineProfile,
    knowledge_type_code: str = DEFAULT_KNOWLEDGE_TYPE_CODE,
    replace_existing: bool = True,
) -> list[models.KnowledgeChunk]:
    """Project high-value nodes for a Task Outline profile into chunks.

    Projection is idempotent when ``replace_existing`` is true: only prior
    chunks with ``chunk_metadata.domain_model == task_outline.v1`` and
    ``chunk_metadata.task_outline_profile_id == profile.id`` are removed.
    Generic semantic textbook chunks are left untouched.
    """
    if replace_existing:
        delete_projected_chunks(
            session,
            normalized_ref_id=profile.normalized_ref_id,
            profile_id=profile.id,
            knowledge_type_code=knowledge_type_code,
        )

    nodes = list(session.scalars(
        select(models.TaskOutlineNode)
        .where(models.TaskOutlineNode.profile_id == profile.id)
        .order_by(
            models.TaskOutlineNode.depth.asc(),
            models.TaskOutlineNode.order_no.asc(),
            models.TaskOutlineNode.id.asc(),
        )
    ))
    chunks: list[models.KnowledgeChunk] = []
    for node in nodes:
        if not should_project_node(node):
            continue
        content = render_node_content(node)
        if not content.strip():
            continue
        chunk = models.KnowledgeChunk(
            normalized_ref_id=profile.normalized_ref_id,
            knowledge_type_code=knowledge_type_code,
            chunk_type=ChunkType.SEMANTIC_BLOCK,
            chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK,
            source_kind=SourceKind.EXTRACTED_FROM_NORMALIZED,
            chunk_index=len(chunks),
            content=content,
            chunk_metadata=chunk_metadata_for_node(profile, node),
            co_emission_origin=None,
            embedding_status=EmbeddingStatus.PENDING,
            source_block_ids=list(node.source_block_ids or []),
            locator=node.locator,
        )
        session.add(chunk)
        chunks.append(chunk)
    session.flush()
    return chunks


def delete_projected_chunks(
    session: Session,
    *,
    normalized_ref_id: str,
    profile_id: str,
    knowledge_type_code: str = DEFAULT_KNOWLEDGE_TYPE_CODE,
) -> int:
    """Delete prior Task Outline projected chunks and return the delete count."""
    existing = list(session.scalars(
        select(models.KnowledgeChunk).where(
            models.KnowledgeChunk.normalized_ref_id == normalized_ref_id,
            models.KnowledgeChunk.knowledge_type_code == knowledge_type_code,
        )
    ))
    ids_to_delete = [
        chunk.id for chunk in existing
        if _is_profile_projection(chunk, profile_id=profile_id)
    ]
    if not ids_to_delete:
        return 0
    session.execute(
        delete(models.KnowledgeChunk).where(models.KnowledgeChunk.id.in_(ids_to_delete))
    )
    session.flush()
    return len(ids_to_delete)


def should_project_node(node: models.TaskOutlineNode) -> bool:
    if node.node_type in MUST_PROJECT_NODE_TYPES:
        return True
    if node.node_type in MAY_PROJECT_NODE_TYPES:
        return bool((node.title or node.summary or node.content or "").strip())
    return False


def render_node_content(node: models.TaskOutlineNode) -> str:
    title = (node.title or "").strip()
    content = (node.content or "").strip()
    summary = (node.summary or "").strip()
    prefix = _prefix_for_node(node)

    parts: list[str] = []
    if title:
        parts.append(f"{prefix}：{title}" if prefix else title)
    elif prefix:
        parts.append(prefix)
    if summary and summary != title:
        parts.append(summary)
    if content and content not in parts:
        parts.append(content)
    return "。".join(part.rstrip("。") for part in parts if part).strip()


def chunk_metadata_for_node(
    profile: models.TaskOutlineProfile,
    node: models.TaskOutlineNode,
) -> dict[str, Any]:
    node_meta = dict(node.node_metadata or {})
    metadata: dict[str, Any] = {
        "semantic_variant": SEMANTIC_VARIANT,
        "domain_model": DOMAIN_MODEL,
        "task_outline_profile_id": profile.id,
        "task_profile": profile.task_profile,
        "textbook_subtype": profile.textbook_subtype,
        "outline_node_id": node.id,
        "node_type": node.node_type,
        "section_type": node.section_type,
        "anchor_role": _anchor_role_for_node(node),
        "section_processing_profile": "task_outline",
        "graph_candidate": False,
    }
    for key in (
        "project_title",
        "task_title",
        "step_no",
        "tools",
        "inputs",
        "outputs",
        "related_artifact_node_ids",
        "artifact_type",
    ):
        if key in node_meta:
            metadata[key] = node_meta[key]
    if "project_node_id" in node_meta:
        metadata["project_node_id"] = node_meta["project_node_id"]
    if "task_node_id" in node_meta:
        metadata["task_node_id"] = node_meta["task_node_id"]
    return metadata


def _prefix_for_node(node: models.TaskOutlineNode) -> str:
    if node.node_type == "project":
        return "项目"
    if node.node_type == "task":
        return "任务"
    if node.node_type == "operation_step":
        step_no = (node.node_metadata or {}).get("step_no")
        return f"操作步骤 {step_no}" if step_no else "操作步骤"
    if node.node_type == "task_artifact":
        return "任务产物"
    if node.node_type == "assessment":
        return "评价要点"
    if node.section_type:
        return _section_label(node.section_type)
    return ""


def _section_label(section_type: str) -> str:
    labels = {
        "task_objective": "任务目标",
        "task_background": "任务背景",
        "task_analysis": "任务分析",
        "knowledge_prepare": "知识准备",
        "operation_steps": "任务实施",
        "task_artifact": "任务产物",
        "source_resource": "资源",
        "task_reflection": "任务思考",
        "assessment": "评价要点",
    }
    return labels.get(section_type, section_type)


def _anchor_role_for_node(node: models.TaskOutlineNode) -> str:
    if node.node_type == "task":
        return "task_overview"
    if node.node_type == "operation_step":
        return "operation_step"
    if node.node_type == "task_artifact":
        return "task_artifact"
    if node.node_type == "assessment":
        return "assessment"
    if node.node_type == "project":
        return "project_overview"
    return node.section_type or node.node_type


def _is_profile_projection(
    chunk: models.KnowledgeChunk,
    *,
    profile_id: str,
) -> bool:
    metadata = chunk.chunk_metadata or {}
    return (
        metadata.get("domain_model") == DOMAIN_MODEL
        and metadata.get("task_outline_profile_id") == profile_id
    )
