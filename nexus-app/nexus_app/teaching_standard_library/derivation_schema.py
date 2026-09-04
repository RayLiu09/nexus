"""Strict one-batch LLM output contract for teaching-standard courses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DERIVATION_SCHEMA_VERSION = "teaching_standard_course_derivation.v1"

ComplexityClass = Literal[
    "foundation_theory_cognition",
    "foundation_theory_case",
    "foundation_tool_data_design",
    "core_single_task",
    "core_multi_task",
    "core_integrated_process_project",
    "core_advanced_management_design_modeling_rd",
    "extension_literacy_cognition",
    "extension_standard_application",
    "extension_technology_tool_project",
    "extension_vocational_undergraduate_advanced",
]


def _ordered_text(values: list[str], *, empty_allowed: bool) -> list[str]:
    normalized = list(
        dict.fromkeys(
            value.strip()
            for value in values
            if isinstance(value, str) and value.strip()
        )
    )
    if not empty_allowed and not normalized:
        raise ValueError("at least one non-empty value is required")
    return normalized


class CourseDerivationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str = Field(min_length=1, max_length=128)
    knowledge_tags: list[str] = Field(min_length=1, max_length=30)
    skill_tags: list[str] = Field(min_length=1, max_length=30)
    tool_tags: list[str] = Field(default_factory=list, max_length=20)
    literacy_tags: list[str] = Field(min_length=1, max_length=20)
    complexity_classification: ComplexityClass
    evidence_block_ids: list[str] = Field(min_length=1, max_length=20)
    tool_evidence_block_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("course_id")
    @classmethod
    def preserve_course_id(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError(
                "course_id must be returned byte-for-byte without whitespace changes"
            )
        return value

    @field_validator("knowledge_tags", "skill_tags", "literacy_tags")
    @classmethod
    def normalize_required_tags(cls, value: list[str]) -> list[str]:
        return _ordered_text(value, empty_allowed=False)

    @field_validator("tool_tags")
    @classmethod
    def normalize_optional_tags(cls, value: list[str]) -> list[str]:
        return _ordered_text(value, empty_allowed=True)

    @field_validator("evidence_block_ids")
    @classmethod
    def normalize_required_evidence(cls, value: list[str]) -> list[str]:
        return _ordered_text(value, empty_allowed=False)

    @field_validator("tool_evidence_block_ids")
    @classmethod
    def normalize_optional_evidence(cls, value: list[str]) -> list[str]:
        return _ordered_text(value, empty_allowed=True)

    @field_validator("knowledge_tags", "skill_tags", "tool_tags", "literacy_tags")
    @classmethod
    def bound_tag_length(cls, value: list[str]) -> list[str]:
        if any(len(item) > 64 for item in value):
            raise ValueError("tag length must not exceed 64 characters")
        return value


class TeachingStandardDerivationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["teaching_standard_course_derivation.v1"]
    training_goal_summary: str = Field(min_length=1, max_length=1000)
    training_goal_evidence_block_ids: list[str] = Field(min_length=1, max_length=20)
    courses: list[CourseDerivationOutput] = Field(min_length=1, max_length=200)

    @field_validator("training_goal_summary")
    @classmethod
    def normalize_summary(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("training_goal_summary must not be empty")
        return value

    @field_validator("training_goal_evidence_block_ids")
    @classmethod
    def normalize_training_evidence(cls, value: list[str]) -> list[str]:
        return _ordered_text(value, empty_allowed=False)
