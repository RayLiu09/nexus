"""Deterministic Slice 2 extraction of professional standard courses."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from nexus_app.knowledge.semantic_repack import _parse_markdown_table
from nexus_app.teaching_standard_library.course_schema import (
    COURSE_SCHEMA_VERSION,
    validate_projection,
)

EXTRACTOR_VERSION = "teaching_standard_course_extractor.v1"

CourseType = Literal["foundation", "core", "extension"]

_GROUP_ALIASES: tuple[tuple[str, CourseType], ...] = (
    ("专业基础课程", "foundation"),
    ("专业核心课程", "core"),
    ("专业拓展课程", "extension"),
    ("专业选修课程", "extension"),
    ("专业拓展课", "extension"),
)
_CORE_HEADERS = {
    "name": ("课程涉及的主要领域",),
    "task": ("典型工作任务描述", "典型工作任务"),
    "content": ("主要教学内容与要求",),
}


@dataclass
class Section:
    course_type: CourseType
    heading: str
    blocks: list[dict[str, Any]]


def extract(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or payload.get("content_type") != "document":
        return None
    blocks = [block for block in payload.get("blocks", []) if isinstance(block, dict)]
    title = _clean(payload.get("title"))
    if not blocks or "专业教学标准" not in f"{title}\n{' '.join(_text(block) for block in blocks)}":
        return None

    sections = _sections(blocks)
    diagnostics: dict[str, int] = {}
    candidates: list[dict[str, Any]] = []
    source_order = 0
    for section in sections:
        extracted, section_diagnostics = (
            _core_courses(section, title)
            if section.course_type == "core"
            else _listed_courses(section, title)
        )
        for key, count in section_diagnostics.items():
            diagnostics[key] = diagnostics.get(key, 0) + count
        for candidate in extracted:
            source_order += 1
            candidate["source_order"] = source_order
            candidates.append(candidate)

    courses = _merge_logical_courses(candidates)
    if not courses:
        diagnostics["course_facts_missing"] = 1
    projection = validate_projection(
        {
            "schema_version": COURSE_SCHEMA_VERSION,
            "extractor_version": EXTRACTOR_VERSION,
            "courses": courses,
            "diagnostics": diagnostics,
        }
    )
    return projection.model_dump(mode="json") if projection is not None else None


def _sections(blocks: list[dict[str, Any]]) -> list[Section]:
    sections: list[Section] = []
    current: Section | None = None
    for block in blocks:
        text = _text(block)
        matched = _match_group(text)
        is_heading = block.get("block_type") in {"heading", "title"}
        if matched is not None:
            course_type, alias, remainder = matched
            if current is not None:
                sections.append(current)
            current = Section(course_type, alias, [])
            if remainder:
                current.blocks.append({**block, "text": remainder})
            continue
        if is_heading:
            if current is not None:
                sections.append(current)
                current = None
            continue
        if current is not None:
            current.blocks.append(block)
    if current is not None:
        sections.append(current)
    return sections


def _match_group(text: str) -> tuple[CourseType, str, str] | None:
    normalized = _heading(text)
    for alias, course_type in _GROUP_ALIASES:
        if normalized == alias:
            return course_type, alias, ""
        if normalized.startswith(alias):
            remainder = normalized[len(alias) :].lstrip(" ：:")
            if remainder.startswith(
                ("设置", "主要包括", "包括", "一般设置")
            ) or text.strip().startswith(alias):
                return course_type, alias, remainder
    return None


def _listed_courses(
    section: Section, source_standard: str
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    courses: list[dict[str, Any]] = []
    for block in section.blocks:
        if block.get("block_type") == "table":
            courses.extend(_simple_course_table(block, section, source_standard))
            continue
        for name in _split_course_names(_text(block)):
            binding = _binding(block, _text(block), None, section.heading)
            courses.append(
                {
                    "standard_course_name": name,
                    "course_type": section.course_type,
                    "typical_work_task_description": None,
                    "teaching_content_requirement": None,
                    "source_standard": source_standard or None,
                    "source_section": section.heading,
                    "source_page": _source_page([binding]),
                    "evidence_bindings": [binding],
                }
            )
    return courses, {}


def _simple_course_table(
    block: dict[str, Any], section: Section, source_standard: str
) -> list[dict[str, Any]]:
    parsed = _parse_markdown_table(_text(block))
    if not parsed:
        return []
    name_index = next(
        (
            index
            for index, header in enumerate(parsed["headers"])
            if "课程名称" in _normalize_header(header)
        ),
        None,
    )
    if name_index is None:
        return []
    courses: list[dict[str, Any]] = []
    for row_index, row in enumerate(parsed["data_rows"], start=1):
        cells = row.get("cells") or []
        if name_index >= len(cells) or _is_repeated_header(cells, parsed["headers"]):
            continue
        name = cells[name_index].strip()
        if not name:
            continue
        sequence = _row_sequence(parsed["headers"], cells)
        binding = _binding(block, row.get("raw") or name, sequence, section.heading, row_index)
        courses.append(
            {
                "standard_course_name": name,
                "course_type": section.course_type,
                "typical_work_task_description": None,
                "teaching_content_requirement": None,
                "source_standard": source_standard or None,
                "source_section": section.heading,
                "source_page": _source_page([binding]),
                "evidence_bindings": [binding],
            }
        )
    return courses


def _core_courses(
    section: Section, source_standard: str
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    courses: list[dict[str, Any]] = []
    diagnostics: dict[str, int] = {}
    table_seen = False
    previous: dict[str, Any] | None = None
    previous_table_id: str | None = None
    previous_sequence: str | None = None
    previous_page: int | None = None
    sequence_targets: dict[tuple[str, str], tuple[dict[str, Any], int | None]] = {}
    for block in section.blocks:
        if block.get("block_type") != "table":
            continue
        parsed = _parse_markdown_table(_text(block))
        if not parsed:
            continue
        indexes = _core_column_indexes(parsed["headers"])
        if indexes is None:
            continue
        table_seen = True
        table_id = _table_id(block)
        page = _page(block)
        for row_index, row in enumerate(parsed["data_rows"], start=1):
            cells = row.get("cells") or []
            if _is_repeated_header(cells, parsed["headers"]):
                continue
            name = _cell(cells, indexes["name"])
            task = _cell(cells, indexes["task"])
            content = _cell(cells, indexes["content"])
            sequence = _row_sequence(parsed["headers"], cells)
            if not name:
                binding = _binding(
                    block,
                    row.get("raw") or " | ".join(cells),
                    sequence,
                    section.heading,
                    row_index,
                )
                target = previous
                target_table_id = previous_table_id
                target_sequence = previous_sequence
                target_page = previous_page
                if table_id and sequence and (table_id, sequence) in sequence_targets:
                    target, target_page = sequence_targets[(table_id, sequence)]
                    target_table_id = table_id
                    target_sequence = sequence
                if (task or content) and _is_compatible_continuation(
                    target,
                    previous_table_id=target_table_id,
                    current_table_id=table_id,
                    previous_sequence=target_sequence,
                    current_sequence=sequence,
                    previous_page=target_page,
                    current_page=page,
                ):
                    target["typical_work_task_description"] = _merge_text(
                        target.get("typical_work_task_description"), task or None
                    )
                    target["teaching_content_requirement"] = _merge_text(
                        target.get("teaching_content_requirement"), content or None
                    )
                    target["evidence_bindings"] = _unique_bindings(
                        [*target["evidence_bindings"], binding]
                    )
                    target["source_page"] = _source_page(target["evidence_bindings"])
                    previous_sequence = sequence or previous_sequence
                    previous_page = page
                    if table_id and sequence:
                        sequence_targets[(table_id, sequence)] = (target, page)
                    continue
                diagnostics["core_course_row_incomplete"] = (
                    diagnostics.get("core_course_row_incomplete", 0) + 1
                )
                continue
            binding = _binding(
                block, row.get("raw") or " | ".join(cells), sequence, section.heading, row_index
            )
            candidate = {
                "standard_course_name": name,
                "course_type": "core",
                "typical_work_task_description": task or None,
                "teaching_content_requirement": content or None,
                "source_standard": source_standard or None,
                "source_section": section.heading,
                "source_page": _source_page([binding]),
                "evidence_bindings": [binding],
            }
            courses.append(candidate)
            previous = candidate
            previous_table_id = table_id
            previous_sequence = sequence
            previous_page = page
            if table_id and sequence:
                sequence_targets[(table_id, sequence)] = (candidate, page)
            if not task or not content:
                diagnostics["core_course_row_incomplete"] = (
                    diagnostics.get("core_course_row_incomplete", 0) + 1
                )
    if not table_seen:
        diagnostics["core_course_table_missing"] = 1
    return courses, diagnostics


def _is_compatible_continuation(
    previous: dict[str, Any] | None,
    *,
    previous_table_id: str | None,
    current_table_id: str | None,
    previous_sequence: str | None,
    current_sequence: str | None,
    previous_page: int | None,
    current_page: int | None,
) -> bool:
    return bool(
        previous is not None
        and previous_table_id
        and previous_table_id == current_table_id
        and (not current_sequence or current_sequence == previous_sequence)
        and previous_page is not None
        and current_page is not None
        and previous_page <= current_page <= previous_page + 1
    )


def _merge_logical_courses(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate in candidates:
        key = (candidate["course_type"], candidate["standard_course_name"])
        existing = merged.get(key)
        if existing is None:
            merged[key] = candidate
            continue
        existing["typical_work_task_description"] = _merge_text(
            existing.get("typical_work_task_description"),
            candidate.get("typical_work_task_description"),
        )
        existing["teaching_content_requirement"] = _merge_text(
            existing.get("teaching_content_requirement"),
            candidate.get("teaching_content_requirement"),
        )
        existing["evidence_bindings"] = _unique_bindings(
            [*existing["evidence_bindings"], *candidate["evidence_bindings"]]
        )
        existing["source_section"] = _merge_text(
            existing.get("source_section"), candidate.get("source_section"), separator="；"
        )
        existing["source_page"] = _source_page(existing["evidence_bindings"])
    return sorted(merged.values(), key=lambda item: item["source_order"])


def _split_course_names(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(
        r"^(?:一般设置\s*\d+\s*门[课程]*[。；;，,]?)?\s*(?:主要)?包括\s*[：:]?", "", cleaned
    )
    cleaned = re.sub(r"(?:等领域的(?:内容|课程)|等专业课程|等课程)\s*[。.]?.*$", "", cleaned)
    cleaned = cleaned.split("。", 1)[0]
    values = [item.strip(" ：:、，,；;。") for item in re.split(r"[、，,；;]", cleaned)]
    return list(dict.fromkeys(item for item in values if 1 < len(item) <= 80))


def _core_column_indexes(headers: list[str]) -> dict[str, int] | None:
    indexes: dict[str, int] = {}
    normalized = [_normalize_header(header) for header in headers]
    for key, aliases in _CORE_HEADERS.items():
        index = next(
            (i for i, header in enumerate(normalized) if any(alias in header for alias in aliases)),
            None,
        )
        if index is None:
            return None
        indexes[key] = index
    return indexes


def _row_sequence(headers: list[str], cells: list[str]) -> str | None:
    index = next(
        (i for i, header in enumerate(headers) if "序号" in _normalize_header(header)), None
    )
    if index is None:
        return None
    return _cell(cells, index) or None


def _binding(
    block: dict[str, Any],
    source_text: str,
    source_sequence: str | None,
    heading: str,
    table_row_index: int | None = None,
) -> dict[str, Any]:
    locator = _locator(block, heading)
    if table_row_index is not None:
        locator["table_row_index"] = table_row_index
    return {
        "source_sequence": source_sequence,
        "source_text": source_text.strip(),
        "evidence_block_ids": [str(block["block_id"])] if block.get("block_id") else [],
        "locator": locator,
    }


def _locator(block: dict[str, Any], heading: str) -> dict[str, Any]:
    source_locator = (
        block.get("source_locator") if isinstance(block.get("source_locator"), dict) else {}
    )
    page = block.get("page")
    if not isinstance(page, int):
        page = source_locator.get("page_no") or source_locator.get("page")
    locator: dict[str, Any] = {"heading_path": [heading]}
    if isinstance(page, int):
        locator["page"] = page
    table_id = block.get("table_id") or source_locator.get("table_id")
    if table_id:
        locator["table_id"] = str(table_id)
    return locator


def _table_id(block: dict[str, Any]) -> str | None:
    source_locator = block.get("source_locator")
    source_locator = source_locator if isinstance(source_locator, dict) else {}
    value = block.get("table_id") or source_locator.get("table_id")
    return str(value) if value else None


def _page(block: dict[str, Any]) -> int | None:
    source_locator = block.get("source_locator")
    source_locator = source_locator if isinstance(source_locator, dict) else {}
    value = block.get("page")
    if not isinstance(value, int):
        value = source_locator.get("page_no") or source_locator.get("page")
    return value if isinstance(value, int) else None


def _source_page(bindings: list[dict[str, Any]]) -> str | None:
    pages = sorted(
        {
            binding.get("locator", {}).get("page")
            for binding in bindings
            if isinstance(binding.get("locator", {}).get("page"), int)
        }
    )
    return ",".join(str(page) for page in pages) or None


def _unique_bindings(bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for binding in bindings:
        locator = binding.get("locator") or {}
        identity = (
            tuple(binding.get("evidence_block_ids") or []),
            binding.get("source_sequence"),
            locator.get("table_row_index"),
            binding.get("source_text"),
        )
        if identity not in seen:
            seen.add(identity)
            result.append(binding)
    return result


def _merge_text(first: str | None, second: str | None, *, separator: str = "\n") -> str | None:
    values = [value.strip() for value in (first, second) if value and value.strip()]
    return separator.join(dict.fromkeys(values)) or None


def _is_repeated_header(cells: list[str], headers: list[str]) -> bool:
    return len(cells) == len(headers) and all(
        _normalize_header(cell) == _normalize_header(header) for cell, header in zip(cells, headers)
    )


def _cell(cells: list[str], index: int | None) -> str:
    return cells[index].strip() if index is not None and index < len(cells) else ""


def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", "", value).strip("：:")


def _heading(value: str) -> str:
    value = value.strip().lstrip("#").strip()
    value = re.sub(r"^[一二三四五六七八九十\d]+[、.．]\s*", "", value)
    value = re.sub(r"^[（(][一二三四五六七八九十\d]+[）)]\s*", "", value)
    return value.strip().rstrip("：:")


def _text(block: dict[str, Any]) -> str:
    return _clean(block.get("text") or block.get("content") or "")


def _clean(value: Any) -> str:
    return str(value).strip()
