"""Deterministic Slice 3 hour, tag, and course-match derivation rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nexus_app import models
from nexus_app.teaching_standard_library.derivation_schema import CourseDerivationOutput

DERIVATION_VERSION = "teaching_standard_course_derivation.v1"
NO_SPECIFIC_TOOL = "无特定工具要求"


@dataclass(frozen=True)
class HourBand:
    course_type: str
    minimum: int
    maximum: int
    suggested: int
    practice_ratio: float


_HOUR_BANDS: dict[str, HourBand] = {
    "foundation_theory_cognition": HourBand("foundation", 24, 48, 24, 1 / 3),
    "foundation_theory_case": HourBand("foundation", 32, 64, 32, 0.5),
    "foundation_tool_data_design": HourBand("foundation", 48, 96, 48, 2 / 3),
    "core_single_task": HourBand("core", 48, 64, 48, 2 / 3),
    "core_multi_task": HourBand("core", 64, 80, 64, 2 / 3),
    "core_integrated_process_project": HourBand("core", 80, 96, 80, 0.7),
    "core_advanced_management_design_modeling_rd": HourBand("core", 96, 112, 96, 0.7),
    "extension_literacy_cognition": HourBand("extension", 16, 32, 16, 0.25),
    "extension_standard_application": HourBand("extension", 32, 48, 32, 0.5),
    "extension_technology_tool_project": HourBand("extension", 48, 64, 48, 2 / 3),
    "extension_vocational_undergraduate_advanced": HourBand(
        "extension", 64, 96, 64, 0.7
    ),
}

_COURSE_TYPE_LABELS = {
    "foundation": "专业基础课程",
    "core": "专业核心课程",
    "extension": "专业拓展课程",
}


class HourRuleValidationError(ValueError):
    pass


def derive_course_fields(
    library: models.TeachingStandardLibrary,
    course: models.TeachingStandardCourse,
    output: CourseDerivationOutput,
) -> dict[str, Any]:
    band = _HOUR_BANDS[output.complexity_classification]
    if band.course_type != course.course_type:
        raise HourRuleValidationError(
            f"complexity class {output.complexity_classification} is invalid for {course.course_type}"
        )

    total = band.suggested
    practice = min(total, _nearest_eight(total * band.practice_ratio))
    if not band.minimum <= total <= band.maximum or practice > total:
        raise HourRuleValidationError(
            "derived course hours violate their deterministic band"
        )

    knowledge = _ordered_unique(output.knowledge_tags)
    skills = _ordered_unique(output.skill_tags)
    tools = _ordered_unique(output.tool_tags) or [NO_SPECIFIC_TOOL]
    literacy = _ordered_unique(output.literacy_tags)
    keywords = _ordered_unique(
        [
            course.standard_course_name,
            *_task_phrases(course.typical_work_task_description),
            *knowledge,
            *skills,
            *(item for item in tools if item != NO_SPECIFIC_TOOL),
            *literacy,
        ]
    )
    return {
        "suggested_total_hours": total,
        "suggested_practice_hours": practice,
        "suggested_hours_range": {
            "min": band.minimum,
            "max": band.maximum,
            "unit": "学时",
        },
        "hours_setting_basis": _hours_basis(library, output, band),
        "knowledge_tags": knowledge,
        "skill_tags": skills,
        "tool_tags": tools,
        "literacy_tags": literacy,
        "match_keywords": "、".join(keywords),
        "match_text": _match_text(library, course, knowledge, skills, tools, literacy),
    }


def _nearest_eight(value: float) -> int:
    return max(0, int((value + 4) // 8) * 8)


def _ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in values if item and item.strip()))


def _task_phrases(value: str | None) -> list[str]:
    if not value:
        return []
    separators = "，。；、\n"
    phrases = [value]
    for separator in separators:
        phrases = [part for phrase in phrases for part in phrase.split(separator)]
    return [phrase.strip() for phrase in phrases if 1 < len(phrase.strip()) <= 64]


def _hours_basis(
    library: models.TeachingStandardLibrary,
    output: CourseDerivationOutput,
    band: HourBand,
) -> str:
    rule_types = sorted({rule.rule_type for rule in library.rules})
    source_rules = ",".join(rule_types) if rule_types else "none"
    return (
        f"{DERIVATION_VERSION}; complexity={output.complexity_classification}; "
        f"range={band.minimum}-{band.maximum}; practice_ratio={band.practice_ratio:.3f}; "
        f"source_rule_types={source_rules}; overlapping_ratios_not_summed=true"
    )


def _match_text(
    library: models.TeachingStandardLibrary,
    course: models.TeachingStandardCourse,
    knowledge: list[str],
    skills: list[str],
    tools: list[str],
    literacy: list[str],
) -> str:
    parts = [
        f"专业：{library.major_name or '未标明'}",
        f"培养层次：{library.education_level or '未标明'}",
        f"课程：{course.standard_course_name}",
        f"课程类型：{_COURSE_TYPE_LABELS[course.course_type]}",
    ]
    if course.typical_work_task_description:
        parts.append(f"典型工作任务：{course.typical_work_task_description}")
    if course.teaching_content_requirement:
        parts.append(f"教学内容与要求：{course.teaching_content_requirement}")
    parts.extend(
        [
            f"知识：{'、'.join(knowledge)}",
            f"技能：{'、'.join(skills)}",
            f"工具：{'、'.join(tools)}",
            f"职业素养：{'、'.join(literacy)}",
        ]
    )
    return "；".join(parts)
