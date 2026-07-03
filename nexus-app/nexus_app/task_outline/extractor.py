"""Minimal deterministic Task Outline extraction for course textbooks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nexus_app.task_outline.detector import (
    TextbookSubtypeDetection,
    detect_course_textbook_subtype,
)
from nexus_app.task_outline.locator import aggregate_locator, block_ids
from nexus_app.task_outline.normalizer import (
    NormalizedBlock,
    normalize_blocks,
    parse_step_no,
    split_label_content,
    text_of,
)
from nexus_app.task_outline.quality import calculate_quality
from nexus_app.task_outline.schemas import (
    TaskOutlineNodeCreate,
    TaskOutlineProfileCreate,
)


@dataclass(frozen=True)
class TaskOutlineExtraction:
    profile: TaskOutlineProfileCreate
    nodes: list[TaskOutlineNodeCreate]
    detection: TextbookSubtypeDetection
    quality: dict


def extract_course_textbook_outline(
    *,
    normalized_ref_id: str,
    asset_version_id: str,
    title: str | None,
    blocks: list[dict[str, Any]],
    body_markdown: str | None = None,
) -> TaskOutlineExtraction:
    detection = detect_course_textbook_subtype(blocks, body_markdown=body_markdown)
    normalized = normalize_blocks(blocks)

    nodes: list[TaskOutlineNodeCreate] = []
    assigned_block_ids: set[str] = set()
    if detection.textbook_subtype == "training_operation":
        nodes, assigned_block_ids = _extract_training_nodes(
            normalized_ref_id=normalized_ref_id,
            normalized_blocks=normalized,
        )

    quality = calculate_quality(
        nodes,
        source_block_count=len(blocks),
        assigned_block_ids=assigned_block_ids,
    )
    profile = TaskOutlineProfileCreate(
        normalized_ref_id=normalized_ref_id,
        asset_version_id=asset_version_id,
        asset_profile="course_textbook",
        title=title,
        textbook_subtype=detection.textbook_subtype,
        task_profile=(
            "textbook_training_operation"
            if detection.textbook_subtype == "training_operation"
            else None
        ),
        subtype_confidence=str(detection.subtype_confidence),
        processing_profile=detection.processing_profile,
        evidence_graph_admission=detection.evidence_graph_admission,
        source_block_ids=detection.source_block_ids,
        quality=quality,
        metadata={
            "subtype_evidence": detection.subtype_evidence,
            "scores": detection.scores,
        },
    )
    return TaskOutlineExtraction(
        profile=profile,
        nodes=nodes,
        detection=detection,
        quality=quality,
    )


def _extract_training_nodes(
    *,
    normalized_ref_id: str,
    normalized_blocks: list[NormalizedBlock],
) -> tuple[list[TaskOutlineNodeCreate], set[str]]:
    nodes: list[TaskOutlineNodeCreate] = []
    assigned_block_ids: set[str] = set()
    order = 0

    current_project_id: str | None = None
    current_task_id: str | None = None
    current_section_type: str | None = None
    current_section_id: str | None = None

    for block in normalized_blocks:
        if block.role == "project_heading":
            order += 1
            current_project_id = _node_id(block, "project")
            current_task_id = None
            current_section_type = None
            current_section_id = None
            nodes.append(_node(
                normalized_ref_id=normalized_ref_id,
                node_id=current_project_id,
                parent_id=None,
                node_type="project",
                title=block.title or block.text,
                order_no=order,
                depth=1,
                blocks=[block.raw],
            ))
            assigned_block_ids.update(block_ids([block.raw]))
            continue

        if block.role == "task_heading":
            order += 1
            current_task_id = _node_id(block, "task")
            current_section_type = None
            current_section_id = None
            nodes.append(_node(
                normalized_ref_id=normalized_ref_id,
                node_id=current_task_id,
                parent_id=current_project_id,
                node_type="task",
                title=block.title or block.text,
                order_no=order,
                depth=2 if current_project_id else 1,
                blocks=[block.raw],
                metadata={
                    "project_node_id": current_project_id,
                    "task_title": block.title or block.text,
                },
            ))
            assigned_block_ids.update(block_ids([block.raw]))
            continue

        if block.section_type is not None:
            if current_task_id is None:
                current_task_id = _implicit_task(
                    normalized_ref_id, nodes, block, order + 1, current_project_id
                )
                order += 1
            current_section_type = block.section_type
            current_section_id = _node_id(block, f"section-{current_section_type}")
            label, inline_content = split_label_content(block.text)
            order += 1
            nodes.append(_node(
                normalized_ref_id=normalized_ref_id,
                node_id=current_section_id,
                parent_id=current_task_id,
                node_type="task_section",
                section_type=current_section_type,
                title=label or block.title or block.text,
                content=inline_content,
                order_no=order,
                depth=3 if current_project_id else 2,
                blocks=[block.raw],
                metadata={"task_node_id": current_task_id},
            ))
            assigned_block_ids.update(block_ids([block.raw]))
            continue

        if block.role == "operation_step" or (
            current_section_type == "operation_steps"
            and parse_step_no(block.text) is not None
        ):
            if current_task_id is None:
                current_task_id = _implicit_task(
                    normalized_ref_id, nodes, block, order + 1, current_project_id
                )
                order += 1
            step_no = block.step_no or parse_step_no(block.text)
            order += 1
            nodes.append(_node(
                normalized_ref_id=normalized_ref_id,
                node_id=_node_id(block, "step"),
                parent_id=current_section_id or current_task_id,
                node_type="operation_step",
                section_type="operation_steps",
                title=_step_title(block.text),
                content=block.text,
                order_no=order,
                depth=4 if current_section_id and current_project_id else 3,
                blocks=[block.raw],
                metadata={
                    "task_node_id": current_task_id,
                    "step_no": step_no,
                    "anchor_role": "operation_step",
                },
            ))
            assigned_block_ids.update(block_ids([block.raw]))
            continue

        if block.role == "artifact" or current_section_type in {"task_artifact", "source_resource"}:
            if current_task_id is None:
                continue
            order += 1
            artifact_type = (
                "source_resource"
                if current_section_type == "source_resource"
                else "task_artifact"
            )
            nodes.append(_node(
                normalized_ref_id=normalized_ref_id,
                node_id=_node_id(block, "artifact"),
                parent_id=current_section_id or current_task_id,
                node_type="task_artifact",
                section_type=current_section_type or "task_artifact",
                title=block.title or _short_text(block.text),
                content=block.text,
                order_no=order,
                depth=4 if current_section_id and current_project_id else 3,
                blocks=[block.raw],
                metadata={
                    "task_node_id": current_task_id,
                    "artifact_type": artifact_type,
                    "anchor_role": "task_artifact",
                },
            ))
            assigned_block_ids.update(block_ids([block.raw]))
            continue

        if block.role == "body" and current_section_id is not None:
            _append_to_section(nodes, current_section_id, block)
            assigned_block_ids.update(block_ids([block.raw]))

    return nodes, assigned_block_ids


def _node(
    *,
    normalized_ref_id: str,
    node_id: str,
    parent_id: str | None,
    node_type: str,
    title: str | None,
    order_no: int,
    depth: int,
    blocks: list[dict[str, Any]],
    section_type: str | None = None,
    content: str | None = None,
    summary: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> TaskOutlineNodeCreate:
    return TaskOutlineNodeCreate(
        id=node_id,
        normalized_ref_id=normalized_ref_id,
        parent_id=parent_id,
        node_type=node_type,
        section_type=section_type,
        title=title,
        content=content,
        summary=summary,
        order_no=order_no,
        depth=depth,
        source_block_ids=block_ids(blocks),
        locator=aggregate_locator(blocks),
        metadata=metadata or {},
    )


def _implicit_task(
    normalized_ref_id: str,
    nodes: list[TaskOutlineNodeCreate],
    block: NormalizedBlock,
    order_no: int,
    current_project_id: str | None,
) -> str:
    node_id = f"node-implicit-task-{block.raw.get('block_id') or block.index}"
    nodes.append(_node(
        normalized_ref_id=normalized_ref_id,
        node_id=node_id,
        parent_id=current_project_id,
        node_type="task",
        title="未命名任务",
        order_no=order_no,
        depth=2 if current_project_id else 1,
        blocks=[block.raw],
        metadata={"implicit": True, "project_node_id": current_project_id},
    ))
    return node_id


def _append_to_section(
    nodes: list[TaskOutlineNodeCreate],
    section_id: str,
    block: NormalizedBlock,
) -> None:
    for index, node in enumerate(nodes):
        if node.id != section_id:
            continue
        content = "\n".join(part for part in [node.content, block.text] if part)
        source_block_ids = list(node.source_block_ids)
        for block_id in block_ids([block.raw]):
            if block_id not in source_block_ids:
                source_block_ids.append(block_id)
        # Pydantic models are immutable only by convention here; replace to keep
        # future changes local if models become frozen.
        nodes[index] = node.model_copy(update={
            "content": content,
            "source_block_ids": source_block_ids,
        })
        return


def _node_id(block: NormalizedBlock, prefix: str) -> str:
    raw_id = block.raw.get("block_id") or str(block.index)
    return f"node-{prefix}-{raw_id}"


def _step_title(text: str) -> str:
    stripped = text.strip()
    if "：" in stripped:
        return stripped.split("：", 1)[0].strip()
    if ":" in stripped:
        return stripped.split(":", 1)[0].strip()
    if len(stripped) <= 48:
        return stripped
    return stripped[:48]


def _short_text(text: str) -> str:
    stripped = text.strip()
    return stripped if len(stripped) <= 80 else stripped[:80]

