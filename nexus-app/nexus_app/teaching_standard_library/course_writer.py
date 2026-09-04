"""Idempotent Slice 2 writer for teaching-standard course facts."""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Any

from nexus_app import models
from nexus_app.teaching_standard_library.course_extractor import EXTRACTOR_VERSION
from nexus_app.teaching_standard_library.course_schema import validate_projection

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_TYPE_CODE = {"foundation": "B", "core": "C", "extension": "E"}
_DIAGNOSTIC_KEYS = {
    "core_course_table_missing",
    "core_course_row_incomplete",
    "course_facts_missing",
}


def write(
    session: "Session",
    library: models.TeachingStandardLibrary,
    payload: dict[str, Any],
) -> list[models.TeachingStandardCourse]:
    projection = validate_projection(payload)
    if projection is None:
        return []
    existing = {
        (course.course_type, course.standard_course_name): course for course in library.courses
    }
    desired_keys = {
        (course.course_type, course.standard_course_name) for course in projection.courses
    }
    for key, course in existing.items():
        if key not in desired_keys:
            session.delete(course)
    session.flush()

    used_ids = {course.course_id for key, course in existing.items() if key in desired_keys}
    written: list[models.TeachingStandardCourse] = []
    for fact in projection.courses:
        key = (fact.course_type, fact.standard_course_name)
        course = existing.get(key)
        source_values = {
            "standard_course_name": fact.standard_course_name,
            "course_type": fact.course_type,
            "typical_work_task_description": fact.typical_work_task_description,
            "teaching_content_requirement": fact.teaching_content_requirement,
            "source_standard": fact.source_standard,
            "source_section": fact.source_section,
            "source_page": fact.source_page,
            "source_order": fact.source_order,
            "evidence_bindings": [item.model_dump(mode="json") for item in fact.evidence_bindings],
            "extractor_version": projection.extractor_version or EXTRACTOR_VERSION,
        }
        source_hash = _source_hash(source_values)
        if course is None:
            course = models.TeachingStandardCourse(
                library_id=library.id,
                course_id=_allocate_course_id(library, fact.course_type, used_ids),
                source_hash=source_hash,
                **source_values,
            )
            session.add(course)
            used_ids.add(course.course_id)
        else:
            if course.source_hash != source_hash:
                _clear_derived_fields(course)
            course.source_hash = source_hash
            for name, value in source_values.items():
                setattr(course, name, value)
        written.append(course)

    flags = dict(library.quality_flags or {})
    for key in _DIAGNOSTIC_KEYS:
        flags.pop(key, None)
    flags.update({key: value for key, value in projection.diagnostics.items() if value})
    library.quality_flags = flags
    session.flush()
    session.expire(library, ["courses"])
    return written


def _allocate_course_id(
    library: models.TeachingStandardLibrary,
    course_type: str,
    used_ids: set[str],
) -> str:
    identity = (
        library.major_code or f"S{hashlib.sha256(library.id.encode()).hexdigest()[:8].upper()}"
    )
    prefix = f"VC{identity}-{_TYPE_CODE[course_type]}"
    used_numbers = {
        int(match.group(1))
        for value in used_ids
        if (match := re.fullmatch(re.escape(prefix) + r"(\d+)", value))
    }
    sequence = 1
    while sequence in used_numbers:
        sequence += 1
    return f"{prefix}{sequence:02d}"


def _source_hash(values: dict[str, Any]) -> str:
    content = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _clear_derived_fields(course: models.TeachingStandardCourse) -> None:
    course.suggested_total_hours = None
    course.suggested_practice_hours = None
    course.suggested_hours_range = None
    course.hours_setting_basis = None
    course.knowledge_tags = []
    course.skill_tags = []
    course.tool_tags = []
    course.literacy_tags = []
    course.match_keywords = None
    course.match_text = None
