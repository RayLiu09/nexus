"""Closed, deterministic payload contract for Slice 1 standard facts."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

DOMAIN_PROFILE = "teaching_standard_library.v1"


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_block_ids: list[str] = Field(default_factory=list)
    locator: dict[str, Any] = Field(default_factory=dict)

    @field_validator("evidence_block_ids")
    @classmethod
    def require_evidence_blocks(cls, value: list[str]) -> list[str]:
        values = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if not values:
            raise ValueError("source fact requires normalized block evidence")
        return values


class OccupationFact(Evidence):
    model_config = ConfigDict(extra="forbid")

    dimension_type: Literal[
        "applied_industry", "occupation_type", "primary_position", "certificate_type"
    ]
    source_code: str | None = None
    source_name: str
    source_text: str | None = None

    @field_validator("source_name")
    @classmethod
    def non_empty_source_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("source_name must not be empty")
        return value


class NumericRule(Evidence):
    model_config = ConfigDict(extra="forbid")

    rule_type: Literal[
        "total_hours",
        "public_foundation_ratio",
        "professional_course_ratio",
        "practice_ratio",
        "elective_ratio",
        "internship_months",
    ]
    comparator: Literal[">=", "<=", "=", "range"]
    numeric_value: float | None = None
    unit: str | None = None
    source_text: str

    @model_validator(mode="after")
    def validate_numeric_value(self) -> "NumericRule":
        if self.numeric_value is None or self.numeric_value <= 0:
            raise ValueError("numeric rule value must be positive")
        if self.unit == "ratio" and self.numeric_value > 1:
            raise ValueError("ratio rule value must not exceed 1")
        # Ratios intentionally are not added together: public/professional,
        # practice and elective populations can overlap in the source standard.
        return self


class TeachingStandardLibraryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["teaching_standard_library.v1"]
    domain_profile: Literal["teaching_standard_library.v1"]
    extractor_version: str
    standard_id: str | None = None
    standard_title: str | None = None
    major_code: str | None = None
    major_name: str | None = None
    education_level: str | None = None
    major_category: dict[str, str | None] = Field(default_factory=dict)
    major_class: dict[str, str | None] = Field(default_factory=dict)
    basic_study_years: str | None = None
    occupations: list[OccupationFact] = Field(default_factory=list)
    course_structures: list[Literal["foundation", "core", "extension"]] = Field(
        default_factory=list
    )
    rules: list[NumericRule] = Field(default_factory=list)
    training_goal_source: dict[str, Any] | None = None
    source_evidence: dict[str, Any] = Field(default_factory=dict)
    quality_flags: dict[str, Any] = Field(default_factory=dict)

    @field_validator("major_code")
    @classmethod
    def normalize_major_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value if re.fullmatch(r"\d{4,6}", value) else None


def validate_payload(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    flags = dict(payload.get("quality_flags") or {}) if isinstance(payload, dict) else {}
    try:
        validated = TeachingStandardLibraryPayload.model_validate(payload).model_dump(mode="json")
    except ValidationError as exc:
        flags["invalid_schema"] = True
        flags["validation_errors"] = [
            ".".join(str(part) for part in error["loc"]) for error in exc.errors()
        ][:8]
        return None, flags
    if not validated.get("major_name"):
        flags["major_identity_missing"] = True
    if not validated.get("standard_id"):
        flags["standard_id_missing"] = True
    if not validated.get("occupations"):
        flags["occupation_orientation_missing"] = True
    validated["quality_flags"] = flags
    return validated, flags
