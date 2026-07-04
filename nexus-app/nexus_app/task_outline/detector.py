"""Deterministic course-textbook subtype detection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nexus_app.task_outline.normalizer import NormalizedBlock, normalize_blocks, text_of


TASK_KEYWORDS = (
    "项目", "任务", "任务目标", "任务背景", "任务分析", "任务实施", "操作步骤",
    "任务思考", "实践训练", "实训", "数据采集表", "任务产物",
)
THEORY_KEYWORDS = (
    "概念", "定义", "原理", "机制", "分类", "影响因素", "知识点", "理论基础",
    "特征", "内涵", "关系模型", "指标体系",
)


@dataclass(frozen=True)
class TextbookSubtypeDetection:
    textbook_subtype: str
    subtype_confidence: float
    processing_profile: str
    evidence_graph_admission: str
    subtype_evidence: list[str]
    source_block_ids: list[str]
    scores: dict[str, float]


def detect_course_textbook_subtype(
    blocks: list[dict[str, Any]],
    *,
    body_markdown: str | None = None,
) -> TextbookSubtypeDetection:
    normalized = normalize_blocks(blocks)
    joined = body_markdown or "\n".join(text_of(block) for block in blocks)

    task_score, task_evidence, task_block_ids = _score_task(normalized, joined)
    theory_score, theory_evidence, theory_block_ids = _score_theory(normalized, joined)
    total_signal = task_score + theory_score

    if total_signal < 4:
        subtype = "unknown"
        confidence = 0.35
    else:
        task_ratio = task_score / total_signal
        theory_ratio = theory_score / total_signal
        if _looks_like_theory_with_practice_drills(normalized, task_score, theory_score):
            subtype = "theory_knowledge"
            confidence = min(0.92, 0.66 + min(theory_score, 12) / 80)
        elif _has_strong_task_outline(normalized):
            subtype = "training_operation"
            confidence = min(0.96, 0.72 + min(task_score, 20) / 100)
        elif task_score >= 6 and theory_score >= 4 and abs(task_ratio - theory_ratio) <= 0.35:
            subtype = "hybrid"
            confidence = min(0.9, 0.55 + min(task_score, theory_score) / 20)
        elif task_score >= 5 and task_ratio >= 0.58:
            subtype = "training_operation"
            confidence = min(0.96, 0.55 + task_ratio * 0.35 + min(task_score, 12) / 80)
        elif theory_score >= 4 and theory_ratio >= 0.58:
            subtype = "theory_knowledge"
            confidence = min(0.94, 0.55 + theory_ratio * 0.32 + min(theory_score, 12) / 90)
        else:
            subtype = "unknown"
            confidence = 0.45

    processing_profile, admission = _routing_for(subtype)
    evidence = _evidence_for(subtype, task_evidence, theory_evidence)
    source_ids = _dedupe(task_block_ids + theory_block_ids)[:20]

    return TextbookSubtypeDetection(
        textbook_subtype=subtype,
        subtype_confidence=round(confidence, 4),
        processing_profile=processing_profile,
        evidence_graph_admission=admission,
        subtype_evidence=evidence,
        source_block_ids=source_ids,
        scores={
            "task_score": round(task_score, 4),
            "theory_score": round(theory_score, 4),
        },
    )


def _has_strong_task_outline(blocks: list[NormalizedBlock]) -> bool:
    """Detect work-task textbooks whose theory keywords live inside tasks."""
    task_count = sum(1 for block in blocks if block.role == "task_heading")
    work_subtask_count = sum(1 for block in blocks if block.role == "work_subtask_heading")
    step_count = sum(1 for block in blocks if block.role == "operation_step")
    section_counts = _section_counts(blocks)
    task_section_count = sum(
        section_counts.get(section_type, 0)
        for section_type in {
            "task_objective",
            "task_background",
            "task_analysis",
            "operation_steps",
            "task_artifact",
            "task_reflection",
        }
    )
    task_cycle_count = min(
        section_counts.get("task_background", 0),
        section_counts.get("task_analysis", 0),
        section_counts.get("operation_steps", 0),
    )
    work_task_count = sum(
        1 for block in blocks
        if block.role == "task_heading" and "工作任务" in block.text
    )
    operation_heading_count = sum(
        1 for block in blocks
        if block.role == "heading" and block.text.strip() in {"任务操作", "任务实施"}
    )
    return (
        (
            work_task_count >= 2
            and work_subtask_count >= 2
            and task_cycle_count >= 2
            and step_count >= 3
        )
        or (
            task_count >= 2
            and task_section_count >= 8
            and task_cycle_count >= 2
            and (step_count >= 3 or operation_heading_count >= 3)
        )
    )


def _looks_like_theory_with_practice_drills(
    blocks: list[NormalizedBlock],
    task_score: float,
    theory_score: float,
) -> bool:
    """Route projectized knowledge textbooks with practice drills to Evidence Graph.

    Some theory textbooks use project/task labels around each knowledge chapter and
    append a short practice operation after the explanation. They should remain
    knowledge assets: the task material is exercise evidence, not the primary
    domain model.
    """
    if theory_score < 6 or task_score < 6:
        return False

    section_counts = _section_counts(blocks)
    task_cycle_count = min(
        section_counts.get("task_background", 0),
        section_counts.get("task_analysis", 0),
        section_counts.get("operation_steps", 0),
    )
    if task_cycle_count >= 2:
        return False

    work_structural_count = sum(
        1 for block in blocks
        if block.role in {"work_subtask_heading"}
        or (block.role == "task_heading" and "工作任务" in block.text)
    )
    if work_structural_count:
        return False

    knowledge_prepare_count = section_counts.get("knowledge_prepare", 0)
    operation_count = section_counts.get("operation_steps", 0)
    objective_count = section_counts.get("task_objective", 0)
    reflective_task_count = section_counts.get("task_reflection", 0)
    analysis_count = section_counts.get("task_analysis", 0)
    background_count = section_counts.get("task_background", 0)
    project_count = sum(1 for block in blocks if block.role == "project_heading")

    return (
        project_count >= 2
        and knowledge_prepare_count >= 2
        and operation_count >= 2
        and objective_count >= 1
        and background_count <= 1
        and analysis_count <= 1
        and reflective_task_count <= max(1, operation_count // 2)
    )


def _section_counts(blocks: list[NormalizedBlock]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for block in blocks:
        if block.section_type is None:
            continue
        counts[block.section_type] = counts.get(block.section_type, 0) + 1
    return counts


def _score_task(
    blocks: list[NormalizedBlock],
    joined: str,
) -> tuple[float, list[str], list[str]]:
    score = 0.0
    evidence: list[str] = []
    block_ids: list[str] = []

    project_count = sum(1 for block in blocks if block.role == "project_heading")
    task_count = sum(1 for block in blocks if block.role == "task_heading")
    step_count = sum(1 for block in blocks if block.role == "operation_step")
    section_count = sum(
        1 for block in blocks
        if block.section_type in {
            "task_objective", "task_background", "task_analysis",
            "operation_steps", "task_artifact",
        }
    )
    artifact_count = sum(1 for block in blocks if block.role == "artifact")

    if project_count:
        score += min(4.0, project_count * 1.5)
        evidence.append("存在项目/模块结构")
    if task_count:
        score += min(5.0, task_count * 2.0)
        evidence.append("存在明确任务标题")
    if section_count:
        score += min(5.0, section_count * 1.0)
        evidence.append("存在任务目标/背景/分析/实施等章节")
    if step_count:
        score += min(4.0, step_count * 1.2)
        evidence.append("存在顺序操作步骤")
    if artifact_count:
        score += min(3.0, artifact_count * 0.8)
        evidence.append("存在表格/图示/任务产物类内容")

    keyword_hits = sum(joined.count(keyword) for keyword in TASK_KEYWORDS)
    if keyword_hits:
        score += min(4.0, keyword_hits * 0.25)
        evidence.append("正文包含任务操作类关键词")

    for block in blocks:
        if (
            block.role in {"project_heading", "task_heading", "operation_step", "artifact"}
            or block.section_type is not None
        ):
            block_id = block.raw.get("block_id")
            if block_id:
                block_ids.append(str(block_id))

    return score, evidence, block_ids


def _score_theory(
    blocks: list[NormalizedBlock],
    joined: str,
) -> tuple[float, list[str], list[str]]:
    score = 0.0
    evidence: list[str] = []
    block_ids: list[str] = []

    keyword_hits = sum(joined.count(keyword) for keyword in THEORY_KEYWORDS)
    if keyword_hits:
        score += min(8.0, keyword_hits * 0.55)
        evidence.append("正文包含概念/定义/原理/机制等理论关键词")

    theory_blocks = [
        block for block in blocks
        if any(keyword in block.text for keyword in THEORY_KEYWORDS)
    ]
    if theory_blocks:
        score += min(4.0, len(theory_blocks) * 0.7)
        evidence.append("多个正文块呈现理论讲解结构")
        block_ids.extend(
            str(block.raw["block_id"])
            for block in theory_blocks
            if block.raw.get("block_id")
        )

    heading_theory = [
        block for block in blocks
        if block.role == "heading"
        and any(keyword in (block.title or block.text) for keyword in THEORY_KEYWORDS)
    ]
    if heading_theory:
        score += min(3.0, len(heading_theory) * 1.0)
        evidence.append("章节标题偏向理论知识组织")
        block_ids.extend(
            str(block.raw["block_id"])
            for block in heading_theory
            if block.raw.get("block_id")
        )

    return score, evidence, block_ids


def _routing_for(subtype: str) -> tuple[str, str]:
    if subtype == "training_operation":
        return "task_outline", "not_recommended"
    if subtype == "theory_knowledge":
        return "evidence_graph", "recommended"
    if subtype == "hybrid":
        return "hybrid", "chapter_selective"
    return "semantic_only", "unknown"


def _evidence_for(
    subtype: str,
    task_evidence: list[str],
    theory_evidence: list[str],
) -> list[str]:
    if subtype == "training_operation":
        return task_evidence[:6]
    if subtype == "theory_knowledge":
        return theory_evidence[:6]
    if subtype == "hybrid":
        return (task_evidence[:3] + theory_evidence[:3])[:6]
    return (task_evidence[:2] + theory_evidence[:2])[:4]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
