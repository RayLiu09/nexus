"""Schema validation and quality flags for `major_profile.v1` payloads."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

DOMAIN_PROFILE = "major_profile.v1"

BLOCKING_FLAGS = frozenset({
    "invalid_schema",
    "invalid_major_code",
    "missing_major_name",
    "missing_occupation_oriented",
    "missing_training_goal",
    "missing_ability_requirements",
    "missing_courses_and_training",
    "missing_foundation_courses",
    "missing_core_courses",
})


class MajorProfileEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    item_index: int | None = Field(default=None, ge=1)
    text: str | None = None
    name: str | None = None
    source_text: str | None = None
    evidence_block_ids: list[str] = Field(default_factory=list)
    locator: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0, le=1)


class MajorProfileCourseItem(MajorProfileEvidenceItem):
    course_group: Literal["foundation", "core", "practice_training"] | None = None
    course_type: str | None = None


class MajorProfileTrainingGoal(BaseModel):
    model_config = ConfigDict(extra="allow")

    text: str
    evidence_block_ids: list[str] = Field(default_factory=list)
    locator: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("text")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("training_goal.text must not be empty")
        return value


class MajorProfileCoursesAndTraining(BaseModel):
    model_config = ConfigDict(extra="allow")

    foundation_courses: list[MajorProfileCourseItem] = Field(default_factory=list)
    core_courses: list[MajorProfileCourseItem] = Field(default_factory=list)
    practice_trainings: list[MajorProfileCourseItem] = Field(default_factory=list)


class MajorProfilePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal["major_profile.v1"]
    domain: Literal["major"] = "major"
    domain_profile: Literal["major_profile.v1"] = "major_profile.v1"
    extractor_version: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    major_code: str
    major_name: str
    education_level: str | None = None
    basic_study_duration: str | None = None
    training_goal: MajorProfileTrainingGoal | None = None
    occupation_oriented: list[MajorProfileEvidenceItem] = Field(default_factory=list)
    ability_requirements: list[MajorProfileEvidenceItem] = Field(default_factory=list)
    courses_and_training: MajorProfileCoursesAndTraining = Field(
        default_factory=MajorProfileCoursesAndTraining
    )
    certificates: list[MajorProfileEvidenceItem] = Field(default_factory=list)
    continuation_majors: list[MajorProfileEvidenceItem] = Field(default_factory=list)
    quality_flags: dict[str, Any] = Field(default_factory=dict)

    @field_validator("major_code")
    @classmethod
    def _valid_major_code(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"\d{4,6}", value):
            raise ValueError("major_code must be 4 to 6 digits")
        return value

    @field_validator("major_name")
    @classmethod
    def _non_empty_major_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("major_name must not be empty")
        return value


def validate_profile_payload(profile: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a normalized payload plus domain quality flags.

    Blocking flags are intentionally limited to structural fields that make the
    domain model unsafe for retrieval or publication. Optional sections such as
    certificates and continuation majors remain warning-level flags.
    """
    flags = dict(profile.get("quality_flags") if isinstance(profile.get("quality_flags"), dict) else {})
    try:
        validated = MajorProfilePayload.model_validate(profile).model_dump(mode="json")
    except ValidationError as exc:
        flags["invalid_schema"] = True
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ()))
            if location == "major_code":
                flags["invalid_major_code"] = True
            if location == "major_name":
                flags["missing_major_name"] = True
        output = dict(profile)
        output["quality_flags"] = flags
        return output, flags

    if not validated.get("occupation_oriented"):
        flags["missing_occupation_oriented"] = True
    if not validated.get("training_goal"):
        flags["missing_training_goal"] = True
    if not validated.get("ability_requirements"):
        flags["missing_ability_requirements"] = True

    courses = validated.get("courses_and_training") or {}
    foundation = courses.get("foundation_courses") or []
    core = courses.get("core_courses") or []
    practice = courses.get("practice_trainings") or []
    if not foundation and not core and not practice:
        flags["missing_courses_and_training"] = True
    if not foundation:
        flags["missing_foundation_courses"] = True
    if not core:
        flags["missing_core_courses"] = True
    if not validated.get("certificates"):
        flags["missing_certificates"] = True
    if not validated.get("continuation_majors"):
        flags["missing_continuation_majors"] = True

    validated["quality_flags"] = flags
    return validated, flags


def profile_payloads(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_profiles = payload.get("profiles")
    if isinstance(raw_profiles, list):
        profiles = [
            item
            for item in raw_profiles
            if isinstance(item, dict) and item.get("schema_version") == DOMAIN_PROFILE
        ]
        if profiles:
            return profiles
    return [payload] if payload.get("schema_version") == DOMAIN_PROFILE else []


def validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a wrapper or single payload and return the same outer shape."""
    profiles = [validate_profile_payload(profile)[0] for profile in profile_payloads(payload)]
    if not profiles:
        return payload
    if len(profiles) == 1 and not isinstance(payload.get("profiles"), list):
        return profiles[0]
    output = dict(profiles[0])
    output["profiles"] = profiles
    output["profile_count"] = len(profiles)
    output["quality_flags"] = aggregate_quality_flags(profiles)
    return output


def aggregate_quality_flags(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for profile in profiles:
        flags = profile.get("quality_flags")
        if not isinstance(flags, dict):
            continue
        for key, value in flags.items():
            if value:
                counts[key] = counts.get(key, 0) + 1
    return counts


def blocking_reasons_from_flags(flags: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for key in sorted(BLOCKING_FLAGS):
        value = flags.get(key)
        if not value:
            continue
        suffix = f" ({value})" if isinstance(value, int) and not isinstance(value, bool) else ""
        reasons.append(f"major_profile.{key}{suffix}")
    return reasons


__all__ = [
    "BLOCKING_FLAGS",
    "DOMAIN_PROFILE",
    "aggregate_quality_flags",
    "blocking_reasons_from_flags",
    "profile_payloads",
    "validate_payload",
    "validate_profile_payload",
]
