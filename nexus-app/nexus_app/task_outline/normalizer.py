"""Heading and key-label normalization for Task Outline extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


PROJECT_RE = re.compile(r"^\s*(项目|模块|单元|工作领域)\s*([一二三四五六七八九十\d]+)\s*(.*)$")
TASK_RE = re.compile(r"^\s*任务\s*([一二三四五六七八九十\d]+)\s*(.*)$")
NUMBERED_STEP_RE = re.compile(r"^\s*(?:步骤\s*)?([0-9]+|[一二三四五六七八九十]+)[\.．、]\s*(.+)$")
CAPTION_RE = re.compile(r"^\s*(图|表)\s*[\d一二三四五六七八九十]+(?:[-－.．]\d+)*\s*(.+)$")

SECTION_LABELS: dict[str, tuple[str, ...]] = {
    "task_objective": ("任务目标", "学习目标", "能力目标", "目标"),
    "task_background": ("任务背景", "背景名称", "背景内容", "场景描述"),
    "task_analysis": ("任务分析", "需求分析"),
    "knowledge_prepare": ("知识准备", "知识回顾", "知识链接"),
    "operation_steps": ("任务实施", "操作步骤", "实施步骤", "任务步骤"),
    "task_artifact": ("任务产物", "实训产物", "成果提交", "数据采集表", "填报表"),
    "source_resource": ("资源", "素材", "原始数据", "附件"),
    "task_reflection": ("任务思考", "拓展训练", "实践训练", "思考题"),
    "assessment": ("评价要点", "检查点", "考核要求", "验收标准"),
}


@dataclass(frozen=True)
class NormalizedBlock:
    raw: dict[str, Any]
    index: int
    text: str
    role: str
    title: str | None = None
    section_type: str | None = None
    step_no: int | None = None


def normalize_blocks(blocks: list[dict[str, Any]]) -> list[NormalizedBlock]:
    return [normalize_block(block, index=i) for i, block in enumerate(blocks)]


def normalize_block(block: dict[str, Any], *, index: int) -> NormalizedBlock:
    text = text_of(block)
    compact = _compact(text)
    block_type = str(block.get("block_type") or "").lower()

    project_match = PROJECT_RE.match(compact)
    if project_match:
        title = compact
        return NormalizedBlock(block, index, text, "project_heading", title=title)

    task_match = TASK_RE.match(compact)
    if task_match:
        return NormalizedBlock(block, index, text, "task_heading", title=compact)

    section_type = section_type_for(compact)
    if section_type is not None:
        title, content = split_label_content(text)
        role = "section_label" if not content else "section_content"
        return NormalizedBlock(
            block, index, text, role, title=title or compact,
            section_type=section_type,
        )

    step = parse_step_no(compact)
    if step is not None:
        return NormalizedBlock(block, index, text, "operation_step", step_no=step)

    if block_type in {"table", "image", "chart"} or CAPTION_RE.match(compact):
        return NormalizedBlock(block, index, text, "artifact", title=compact)

    if block_type in {"heading", "title"}:
        return NormalizedBlock(block, index, text, "heading", title=compact)

    return NormalizedBlock(block, index, text, "body")


def section_type_for(text: str) -> str | None:
    normalized = text.strip().rstrip("：:")
    prefix = re.split(r"[:：\s]", normalized, maxsplit=1)[0]
    for section_type, labels in SECTION_LABELS.items():
        if normalized in labels or prefix in labels:
            return section_type
        if any(normalized.startswith(f"{label}：") for label in labels):
            return section_type
    return None


def split_label_content(text: str) -> tuple[str | None, str | None]:
    stripped = text.strip()
    if "：" in stripped:
        left, right = stripped.split("：", 1)
    elif ":" in stripped:
        left, right = stripped.split(":", 1)
    else:
        return stripped or None, None
    return left.strip() or None, right.strip() or None


def parse_step_no(text: str) -> int | None:
    match = NUMBERED_STEP_RE.match(text)
    if not match:
        return None
    token = match.group(1)
    if token.isdigit():
        return int(token)
    return _chinese_numeral_to_int(token)


def text_of(block: dict[str, Any]) -> str:
    value = (
        block.get("text")
        or block.get("content")
        or block.get("markdown")
        or block.get("caption")
        or ""
    )
    return str(value).strip()


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _chinese_numeral_to_int(value: str) -> int | None:
    digits = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if value == "十":
        return 10
    if len(value) == 1:
        return digits.get(value)
    if value.startswith("十"):
        tail = digits.get(value[1:], 0)
        return 10 + tail
    if "十" in value:
        head, _, tail = value.partition("十")
        return digits.get(head, 0) * 10 + digits.get(tail, 0)
    return None

