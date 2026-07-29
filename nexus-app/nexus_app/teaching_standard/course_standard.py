"""Evidence-bound extraction for course-standard content-requirement tables."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

DOMAIN_PROFILE = "course_standard.v1"
EXTRACTOR_VERSION = "course_standard_table_extractor.v1"
_BULLET_PREFIX = re.compile(r"(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d+[.、．])\s*")
_MODULE_HEADERS = ("课程模块", "项目", "章", "节", "工作模块")
_CONTENT_HEADERS = ("课程内容", "教学任务", "工作任务", "学习单元")
_SKILL_HEADERS = ("技能要求", "技能内容")
_KNOWLEDGE_HEADERS = ("知识要求", "知识内容")
_PERIOD_HEADERS = ("学时", "课时")
_COURSE_STANDARD_SUFFIX = re.compile(r"课程标准(?:\s*[（(][^（）()]*[）)])?\s*$")
_TITLE_FILE_EXTENSION = re.compile(r"\.(?:pdf|docx?|xlsx?|pptx?)$", re.IGNORECASE)
_TITLE_ALLOWED = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]")


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
    source_title = str(payload.get("title") or "").strip()
    course_title = _course_title(source_title)
    if not course_title:
        return CourseStandardExtractionResult(None, "course_title_missing")

    rows: list[dict[str, Any]] = []
    table_seen = False
    target_table_seen = False
    incomplete = False
    for block in blocks:
        if not isinstance(block, dict) or block.get("block_type") != "table":
            continue
        table_seen = True
        table = _parse_course_table(str(block.get("content") or block.get("text") or ""))
        if table is None:
            continue
        target_table_seen = True
        for row in table["rows"]:
            module = row["course_module"]
            content = row["course_content"]
            skills = _split_items(row["skill_requirement"])
            knowledge = _split_items(row["knowledge_requirement"])
            if not module or not content or not skills or not knowledge:
                incomplete = True
                continue
            rows.append(
                {
                    "row_index": row["row_index"],
                    "course_module": module,
                    "course_contents": [content],
                    "skill_requirements": skills,
                    "knowledge_requirements": knowledge,
                    "evidence": {
                        "source_block_ids": [str(block.get("block_id") or "")],
                        "locator": {"table_row_index": row["row_index"]},
                        "source_row": row["raw"],
                    },
                }
            )

    if not rows:
        if target_table_seen or incomplete:
            return CourseStandardExtractionResult(None, "course_content_row_incomplete")
        return CourseStandardExtractionResult(None, "course_content_table_missing" if not table_seen else "course_content_headers_missing")
    if incomplete:
        return CourseStandardExtractionResult(None, "course_content_row_incomplete")
    return CourseStandardExtractionResult(
        {
            "schema_version": DOMAIN_PROFILE,
            "extractor_version": EXTRACTOR_VERSION,
            "course_title": course_title,
            "source_title": source_title,
            "rows": rows,
            "extractor": {"strategy": "rule", "version": EXTRACTOR_VERSION, "confidence": 1.0},
        }
    )


def _course_title(value: object) -> str:
    """Return a display-safe root name from the literal normalized title."""
    title = str(value or "").strip()
    title = _TITLE_FILE_EXTENSION.sub("", title)
    title = _COURSE_STANDARD_SUFFIX.sub("", title)
    title = _TITLE_ALLOWED.sub("", title)
    return re.sub(r"课程标准$", "", title).strip()


def _parse_course_table(content: str) -> dict[str, Any] | None:
    """Parse normal and two-row-header Markdown tables without prose inference."""
    raw_rows = [_split_markdown_row(line) for line in content.splitlines() if line.strip().startswith("|")]
    raw_rows = [row for row in raw_rows if row and not _is_separator_row(row)]
    if not raw_rows:
        return None

    header_index = next(
        (
            index
            for index, row in enumerate(raw_rows)
            if _find_alias(row, _SKILL_HEADERS) is not None
            and _find_alias(row, _KNOWLEDGE_HEADERS) is not None
        ),
        None,
    )
    if header_index is None:
        return None
    header_rows = raw_rows[: header_index + 1]
    header = raw_rows[header_index]
    # A normalized PDF table can carry a group label in the first header row
    # and its concrete column name in the row beneath it. Resolve by column,
    # preferring the closest header to the data rows.
    module_index = _find_alias_in_header_rows(header_rows, _MODULE_HEADERS)
    content_index = _find_alias_in_header_rows(header_rows, _CONTENT_HEADERS)
    skill_index = _find_alias_in_header_rows(header_rows, _SKILL_HEADERS)
    knowledge_index = _find_alias_in_header_rows(header_rows, _KNOWLEDGE_HEADERS)
    period_present = _find_alias_in_header_rows(header_rows, _PERIOD_HEADERS) is not None
    if None in {module_index, content_index, skill_index, knowledge_index} or not period_present:
        return None

    rows: list[dict[str, Any]] = []
    current_module = ""
    for source_index, cells in enumerate(raw_rows[header_index + 1 :], start=1):
        if _is_repeated_header(cells, header):
            continue
        required_index = max(module_index, content_index, skill_index, knowledge_index)
        if len(cells) <= required_index:
            continue
        module = cells[module_index].strip()
        content = cells[content_index].strip()
        skill = cells[skill_index].strip()
        knowledge = cells[knowledge_index].strip()
        # PDF table merges leave the repeated module cell blank on following
        # rows. Inherit only within this contiguous normalized table; never
        # derive a module from prose or a different block.
        if module:
            current_module = module
        if not current_module or _is_total_row(module, content, skill, knowledge):
            continue
        rows.append(
            {
                "row_index": source_index,
                "course_module": current_module,
                "course_content": content,
                "skill_requirement": skill,
                "knowledge_requirement": knowledge,
                "raw": "| " + " | ".join(cells) + " |",
            }
        )
    return {"rows": rows}


def _is_total_row(*values: str) -> bool:
    return any("合计" in value for value in values)


def _split_markdown_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    return all(re.fullmatch(r"[:\-\s]+", cell or "") is not None for cell in cells)


def _find_alias(headers: list[str], aliases: tuple[str, ...]) -> int | None:
    normalized = [_normalize_header(header) for header in headers]
    return next(
        (index for index, value in enumerate(normalized) if any(alias in value for alias in aliases)),
        None,
    )


def _find_alias_in_header_rows(
    header_rows: list[list[str]], aliases: tuple[str, ...],
) -> int | None:
    for row in reversed(header_rows):
        index = _find_alias(row, aliases)
        if index is not None:
            return index
    return None


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
        for item in re.split(r"\n|\s+/\s+|(?<!^)(?=(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d{1,2}[.、．]))", normalized)
    ]
    return list(dict.fromkeys(item for item in values if item))
