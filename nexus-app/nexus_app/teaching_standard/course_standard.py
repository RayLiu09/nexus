"""Evidence-bound extraction for course-standard content-requirement tables."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from nexus_app.knowledge.semantic_repack import _parse_markdown_table

DOMAIN_PROFILE = "course_standard.v1"
EXTRACTOR_VERSION = "course_standard_table_extractor.v1"
_REQUIRED_COLUMNS = ("课程模块", "教学任务", "技能要求", "知识要求")
_BULLET_PREFIX = re.compile(r"(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d+[.、．])\s*")


@dataclass(frozen=True)
class CourseStandardExtractionResult:
    payload: dict[str, Any] | None
    failure_reason: str | None = None


def extract_with_diagnostics(payload: dict[str, Any]) -> CourseStandardExtractionResult:
    """Extract literal course-module/task/skill/knowledge table values only."""
    if not isinstance(payload, dict) or payload.get("content_type") != "document":
        return CourseStandardExtractionResult(None, "invalid_normalized_document")
    blocks = payload.get("blocks")
    if not isinstance(blocks, list):
        return CourseStandardExtractionResult(None, "invalid_normalized_document")

    rows: list[dict[str, Any]] = []
    table_seen = False
    target_table_seen = False
    incomplete = False
    for block in blocks:
        if not isinstance(block, dict) or block.get("block_type") != "table":
            continue
        table_seen = True
        parsed = _parse_markdown_table(str(block.get("content") or block.get("text") or ""))
        if not parsed:
            continue
        indexes = _column_indexes(parsed["headers"])
        if indexes is None:
            continue
        target_table_seen = True
        for row_index, row in enumerate(parsed["data_rows"], start=1):
            cells = row["cells"]
            if _is_repeated_header(cells, parsed["headers"]):
                continue
            module = cells[indexes["course_module"]].strip()
            tasks = _split_items(cells[indexes["teaching_task"]])
            skills = _split_items(cells[indexes["skill_requirement"]])
            knowledge = _split_items(cells[indexes["knowledge_requirement"]])
            if not module or not tasks or not skills or not knowledge:
                incomplete = True
                continue
            rows.append(
                {
                    "row_index": row_index,
                    "course_module": module,
                    "teaching_tasks": tasks,
                    "skill_requirements": skills,
                    "knowledge_requirements": knowledge,
                    "evidence": {
                        "source_block_ids": [str(block.get("block_id") or "")],
                        "locator": {"table_row_index": row_index},
                        "source_row": str(row.get("raw") or ""),
                    },
                }
            )

    if not rows:
        if target_table_seen or incomplete:
            return CourseStandardExtractionResult(None, "course_content_row_incomplete")
        return CourseStandardExtractionResult(
            None, "course_content_table_missing" if not table_seen else "course_content_headers_missing"
        )
    if incomplete:
        return CourseStandardExtractionResult(None, "course_content_row_incomplete")
    return CourseStandardExtractionResult(
        {
            "schema_version": DOMAIN_PROFILE,
            "extractor_version": EXTRACTOR_VERSION,
            "rows": rows,
            "extractor": {"strategy": "rule", "version": EXTRACTOR_VERSION, "confidence": 1.0},
        }
    )


def _column_indexes(headers: list[str]) -> dict[str, int] | None:
    normalized = [_normalize_header(header) for header in headers]
    mapping = {
        "course_module": "课程模块",
        "teaching_task": "教学任务",
        "skill_requirement": "技能要求",
        "knowledge_requirement": "知识要求",
    }
    indexes: dict[str, int] = {}
    for key, required in mapping.items():
        index = next((i for i, value in enumerate(normalized) if required in value), None)
        if index is None:
            return None
        indexes[key] = index
    return indexes


def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", "", value).strip("：:")


def _is_repeated_header(cells: list[str], headers: list[str]) -> bool:
    return len(cells) == len(headers) and all(
        _normalize_header(cell) == _normalize_header(header)
        for cell, header in zip(cells, headers)
    )


def _split_items(value: str) -> list[str]:
    normalized = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    # `_parse_markdown_table` normalizes HTML line breaks to ` / ` in some
    # MinerU table cells. Treat that exact separator like a line break while
    # leaving ordinary slash-bearing values untouched.
    values = [
        _BULLET_PREFIX.sub("", item).strip()
        for item in re.split(r"\n|\s+/\s+", normalized)
    ]
    return list(dict.fromkeys(item for item in values if item))
