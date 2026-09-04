"""Validated source-fact contract for Slice 2 standard courses."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

COURSE_SCHEMA_VERSION = "teaching_standard_course.v1"


class CourseEvidenceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_sequence: str | None = None
    source_text: str
    evidence_block_ids: list[str] = Field(min_length=1)
    locator: dict[str, Any] = Field(default_factory=dict)

    @field_validator("evidence_block_ids")
    @classmethod
    def unique_block_ids(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if not normalized:
            raise ValueError("at least one non-empty evidence block id is required")
        return normalized


class CourseFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    standard_course_name: str
    course_type: Literal["foundation", "core", "extension"]
    source_order: int = Field(ge=1)
    typical_work_task_description: str | None = None
    teaching_content_requirement: str | None = None
    source_standard: str | None = None
    source_section: str
    source_page: str | None = None
    evidence_bindings: list[CourseEvidenceBinding] = Field(min_length=1)

    @field_validator("standard_course_name", "source_section")
    @classmethod
    def non_empty_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("course name and source section must not be empty")
        return value


class CourseProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["teaching_standard_course.v1"]
    extractor_version: str
    courses: list[CourseFact] = Field(default_factory=list)
    diagnostics: dict[str, int] = Field(default_factory=dict)


def validate_projection(payload: dict[str, Any]) -> CourseProjection | None:
    try:
        return CourseProjection.model_validate(payload)
    except ValidationError:
        return None
