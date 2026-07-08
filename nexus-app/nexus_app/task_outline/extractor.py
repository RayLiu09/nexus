"""Minimal deterministic Task Outline extraction for course textbooks."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
import re
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
from nexus_app.task_outline.subtype_llm import TextbookSubtypeArbiterProtocol


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
    subtype_arbiter: TextbookSubtypeArbiterProtocol | None = None,
) -> TaskOutlineExtraction:
    detection = detect_course_textbook_subtype(blocks, body_markdown=body_markdown)
    if subtype_arbiter is not None:
        detection = subtype_arbiter.arbitrate(
            blocks=blocks,
            body_markdown=body_markdown,
            rule_detection=detection,
        )
    normalized = normalize_blocks(blocks)

    nodes: list[TaskOutlineNodeCreate] = []
    assigned_block_ids: set[str] = set()
    if detection.textbook_subtype == "training_operation":
        nodes, assigned_block_ids = _extract_training_nodes(
            normalized_ref_id=normalized_ref_id,
            normalized_blocks=normalized,
            body_markdown=body_markdown,
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
    body_markdown: str | None = None,
) -> tuple[list[TaskOutlineNodeCreate], set[str]]:
    nodes: list[TaskOutlineNodeCreate] = []
    assigned_block_ids: set[str] = set()
    order = 0

    current_project_id: str | None = None
    current_work_task_id: str | None = None
    current_task_id: str | None = None
    current_task_heading_level: int | None = None
    current_section_type: str | None = None
    current_section_id: str | None = None
    current_step_id: str | None = None
    task_heading_stack: list[tuple[int, str]] = []

    for block in normalized_blocks:
        if block.role == "project_heading":
            order += 1
            current_project_id = _node_id(block, "project")
            current_work_task_id = None
            current_task_id = None
            current_task_heading_level = None
            current_section_type = None
            current_section_id = None
            current_step_id = None
            task_heading_stack.clear()
            nodes.append(_node(
                normalized_ref_id=normalized_ref_id,
                node_id=current_project_id,
                parent_id=None,
                node_type="project",
                title=block.title or block.text,
                order_no=order,
                depth=1,
                blocks=[block.raw],
                metadata={
                    "heading_level": block.heading_level,
                    "hierarchy_source": "mineru_heading_level" if block.heading_level else "task_outline_fallback",
                },
            ))
            assigned_block_ids.update(block_ids([block.raw]))
            continue

        if block.role == "task_heading":
            order += 1
            current_task_id = _node_id(block, "task")
            current_task_heading_level = block.heading_level
            current_work_task_id = current_task_id
            current_section_type = None
            current_section_id = None
            current_step_id = None
            parent_id, hierarchy_source = _task_parent_from_heading_level(
                heading_level=block.heading_level,
                heading_stack=task_heading_stack,
                current_project_id=current_project_id,
            )
            nodes.append(_node(
                normalized_ref_id=normalized_ref_id,
                node_id=current_task_id,
                parent_id=parent_id,
                node_type="task",
                title=block.title or block.text,
                order_no=order,
                depth=_child_depth(parent_id, nodes),
                blocks=[block.raw],
                metadata={
                    "project_node_id": current_project_id,
                    "task_title": block.title or block.text,
                    "task_level": "work_task",
                    "heading_level": block.heading_level,
                    "hierarchy_source": hierarchy_source,
                },
            ))
            _push_task_heading(task_heading_stack, block.heading_level, current_task_id)
            assigned_block_ids.update(block_ids([block.raw]))
            continue

        if block.role == "work_subtask_heading":
            order += 1
            current_task_id = _node_id(block, "task")
            current_task_heading_level = block.heading_level
            current_section_type = None
            current_section_id = None
            current_step_id = None
            parent_id, hierarchy_source = _task_parent_from_heading_level(
                heading_level=block.heading_level,
                heading_stack=task_heading_stack,
                current_project_id=current_project_id,
            )
            if parent_id == current_project_id and current_work_task_id is not None:
                parent_id = current_work_task_id
                hierarchy_source = "task_numbering_fallback_after_mineru_level_tie"
            nodes.append(_node(
                normalized_ref_id=normalized_ref_id,
                node_id=current_task_id,
                parent_id=parent_id,
                node_type="task",
                title=block.title or block.text,
                order_no=order,
                depth=_child_depth(parent_id, nodes),
                blocks=[block.raw],
                metadata={
                    "project_node_id": current_project_id,
                    "work_task_node_id": current_work_task_id,
                    "task_title": block.title or block.text,
                    "task_level": "work_subtask",
                    "heading_level": block.heading_level,
                    "hierarchy_source": hierarchy_source,
                },
            ))
            _push_task_heading(task_heading_stack, block.heading_level, current_task_id)
            assigned_block_ids.update(block_ids([block.raw]))
            continue

        if block.section_type is not None:
            if current_task_id is None:
                continue
            current_section_type = block.section_type
            current_section_id = _node_id(block, f"section-{current_section_type}")
            current_step_id = None
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
                depth=_child_depth(current_task_id, nodes),
                blocks=[block.raw],
                metadata={
                    "task_node_id": current_task_id,
                    "task_heading_level": current_task_heading_level,
                },
            ))
            assigned_block_ids.update(block_ids([block.raw]))
            continue

        if block.role == "outline_boundary":
            current_section_type = None
            current_section_id = None
            current_step_id = None
            assigned_block_ids.update(block_ids([block.raw]))
            continue

        if block.role == "operation_step" or (
            current_section_type == "operation_steps"
            and parse_step_no(block.text) is not None
        ):
            if current_section_type != "operation_steps":
                if current_section_id is not None:
                    _append_to_section(nodes, current_section_id, block, body_markdown=body_markdown)
                    assigned_block_ids.update(block_ids([block.raw]))
                continue
            if current_task_id is None:
                continue
            step_no = block.step_no or parse_step_no(block.text)
            current_step_id = _node_id(block, "step")
            order += 1
            nodes.append(_node(
                normalized_ref_id=normalized_ref_id,
                node_id=current_step_id,
                parent_id=current_section_id or current_task_id,
                node_type="operation_step",
                section_type="operation_steps",
                title=_step_title(block.text),
                content=block.text,
                order_no=order,
                depth=_child_depth(current_section_id or current_task_id, nodes),
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
            content = _block_content(block, body_markdown)
            if not content:
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
                title=_artifact_title(block, content),
                content=content,
                order_no=order,
                depth=_child_depth(current_section_id or current_task_id, nodes),
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
            append_target_id = (
                current_step_id
                if current_section_type == "operation_steps" and current_step_id is not None
                else current_section_id
            )
            _append_to_section(nodes, append_target_id, block, body_markdown=body_markdown)
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


def _child_depth(parent_id: str | None, nodes: list[TaskOutlineNodeCreate]) -> int:
    if parent_id is None:
        return 1
    parent = next((node for node in reversed(nodes) if node.id == parent_id), None)
    return (parent.depth + 1) if parent is not None else 1


def _task_parent_from_heading_level(
    *,
    heading_level: int | None,
    heading_stack: list[tuple[int, str]],
    current_project_id: str | None,
) -> tuple[str | None, str]:
    """Resolve task parent from MinerU heading levels before using fallbacks."""
    if heading_level is not None:
        for level, node_id in reversed(heading_stack):
            if level < heading_level:
                return node_id, "mineru_heading_level"
        return current_project_id, "mineru_heading_level"
    return current_project_id, "task_outline_fallback"


def _push_task_heading(
    heading_stack: list[tuple[int, str]],
    heading_level: int | None,
    node_id: str,
) -> None:
    if heading_level is None:
        return
    while heading_stack and heading_stack[-1][0] >= heading_level:
        heading_stack.pop()
    heading_stack.append((heading_level, node_id))


def _implicit_task(
    normalized_ref_id: str,
    nodes: list[TaskOutlineNodeCreate],
    block: NormalizedBlock,
    order_no: int,
    current_project_id: str | None,
) -> str:
    node_id = _node_id(block, "implicit-task")
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
    body_markdown: str | None = None,
) -> None:
    for index, node in enumerate(nodes):
        if node.id != section_id:
            continue
        block_content = _block_content(block, body_markdown)
        if not block_content:
            return
        content = "\n".join(part for part in [node.content, block_content] if part)
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
    digest = sha1(f"{prefix}:{raw_id}".encode("utf-8")).hexdigest()[:12]
    safe_prefix = re.sub(r"[^a-zA-Z0-9]+", "-", prefix).strip("-")[:14]
    return f"node-{safe_prefix}-{digest}"


def _block_content(block: NormalizedBlock, body_markdown: str | None) -> str:
    markdown = _markdown_slice(block.raw, body_markdown)
    if markdown:
        return markdown
    return block.text


def _markdown_slice(block: dict[str, Any], body_markdown: str | None) -> str | None:
    if not body_markdown:
        return None
    raw_range = block.get("md_char_range")
    if (
        not isinstance(raw_range, list)
        or len(raw_range) != 2
        or not all(isinstance(value, int) for value in raw_range)
    ):
        return None
    start, end = raw_range
    if start < 0 or end <= start or start >= len(body_markdown):
        return None
    return body_markdown[start:min(end, len(body_markdown))].strip() or None


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


def _artifact_title(block: NormalizedBlock, content: str) -> str:
    if block.title and not block.title.strip().startswith("|"):
        return block.title
    first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
    bold_match = re.match(r"^\*\*(.+?)\*\*$", first_line)
    if bold_match:
        return _short_text(bold_match.group(1))
    return _short_text(first_line or content)
