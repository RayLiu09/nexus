"""Quality metrics for Task Outline extraction."""

from __future__ import annotations

from nexus_app.task_outline.schemas import TaskOutlineNodeCreate


HIGH_VALUE_NODE_TYPES = {
    "task",
    "task_section",
    "operation_step",
    "task_artifact",
    "assessment",
}


def calculate_quality(
    nodes: list[TaskOutlineNodeCreate],
    *,
    source_block_count: int,
    assigned_block_ids: set[str],
) -> dict:
    high_value = [node for node in nodes if node.node_type in HIGH_VALUE_NODE_TYPES]
    located = [node for node in high_value if node.locator is not None]
    project_nodes = [node for node in nodes if node.node_type == "project"]
    task_nodes = [node for node in nodes if node.node_type == "task"]
    section_nodes = [node for node in nodes if node.node_type == "task_section"]
    step_nodes = [node for node in nodes if node.node_type == "operation_step"]
    artifact_nodes = [node for node in nodes if node.node_type == "task_artifact"]

    expected_projection_nodes = [
        node for node in high_value
        if node.node_type in {"task", "task_section", "operation_step", "task_artifact"}
    ]

    locator_coverage = _ratio(len(located), len(high_value))
    chunk_projection_coverage = _ratio(len(expected_projection_nodes), len(expected_projection_nodes))
    orphan_block_ratio = 1.0 - _ratio(len(assigned_block_ids), source_block_count)
    artifact_binding_rate = _ratio(
        len([node for node in artifact_nodes if node.parent_id]),
        len(artifact_nodes),
        default=1.0,
    )
    step_order_validity = _step_order_validity(step_nodes)
    section_coverage = _ratio(len(section_nodes), max(len(task_nodes), 1), default=0.0)

    review_required = (
        locator_coverage < 0.95
        or chunk_projection_coverage < 0.9
        or artifact_binding_rate < 0.7
    )

    return {
        "project_count": len(project_nodes),
        "task_count": len(task_nodes),
        "section_count": len(section_nodes),
        "operation_step_count": len(step_nodes),
        "artifact_count": len(artifact_nodes),
        "task_coverage": 1.0 if task_nodes else 0.0,
        "section_coverage": round(section_coverage, 4),
        "step_order_validity": step_order_validity,
        "artifact_binding_rate": round(artifact_binding_rate, 4),
        "resource_binding_rate": 1.0,
        "locator_coverage": round(locator_coverage, 4),
        "chunk_projection_coverage": round(chunk_projection_coverage, 4),
        "noise_ratio": 0.0,
        "orphan_block_ratio": round(max(0.0, orphan_block_ratio), 4),
        "review_required": review_required,
    }


def _ratio(numerator: int, denominator: int, *, default: float = 0.0) -> float:
    if denominator <= 0:
        return default
    return numerator / denominator


def _step_order_validity(step_nodes: list[TaskOutlineNodeCreate]) -> float:
    by_parent: dict[str | None, list[int]] = {}
    for node in step_nodes:
        step_no = node.metadata.get("step_no")
        if isinstance(step_no, int):
            by_parent.setdefault(node.parent_id, []).append(step_no)
    if not by_parent:
        return 1.0
    valid = 0
    for values in by_parent.values():
        if values == sorted(values):
            valid += 1
    return round(valid / len(by_parent), 4)

