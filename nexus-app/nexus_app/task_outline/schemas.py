"""Schemas for Task Outline profile and node persistence."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


TEXTBOOK_SUBTYPES = {
    "theory_knowledge",
    "training_operation",
    "hybrid",
    "unknown",
}
PROCESSING_PROFILES = {
    "evidence_graph",
    "task_outline",
    "hybrid",
    "semantic_only",
}
EVIDENCE_GRAPH_ADMISSIONS = {
    "recommended",
    "not_recommended",
    "chapter_selective",
    "unknown",
}
TASK_PROFILES = {
    "textbook_training_operation",
    "enterprise_training_task",
}
NODE_TYPES = {
    "book",
    "project",
    "task",
    "task_section",
    "operation_step",
    "task_artifact",
    "assessment",
}
SECTION_TYPES = {
    "task_objective",
    "task_background",
    "task_analysis",
    "knowledge_prepare",
    "operation_steps",
    "task_artifact",
    "source_resource",
    "task_reflection",
    "assessment",
}


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TaskOutlineProfileCreate(BaseModel):
    normalized_ref_id: str = Field(min_length=1, max_length=36)
    asset_version_id: str = Field(min_length=1, max_length=36)
    asset_profile: str = Field(min_length=1, max_length=64)
    title: str | None = Field(default=None, max_length=512)
    textbook_subtype: str | None = Field(default=None, max_length=64)
    task_profile: str | None = Field(default=None, max_length=64)
    subtype_confidence: Decimal | None = Field(default=None, ge=0, le=1)
    processing_profile: str = Field(min_length=1, max_length=64)
    evidence_graph_admission: str = Field(min_length=1, max_length=64)
    source_block_ids: list[str] = Field(default_factory=list)
    quality: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("textbook_subtype")
    @classmethod
    def validate_textbook_subtype(cls, value: str | None) -> str | None:
        return _validate_optional_choice(value, TEXTBOOK_SUBTYPES, "textbook_subtype")

    @field_validator("task_profile")
    @classmethod
    def validate_task_profile(cls, value: str | None) -> str | None:
        return _validate_optional_choice(value, TASK_PROFILES, "task_profile")

    @field_validator("processing_profile")
    @classmethod
    def validate_processing_profile(cls, value: str) -> str:
        return _validate_required_choice(value, PROCESSING_PROFILES, "processing_profile")

    @field_validator("evidence_graph_admission")
    @classmethod
    def validate_evidence_graph_admission(cls, value: str) -> str:
        return _validate_required_choice(
            value, EVIDENCE_GRAPH_ADMISSIONS, "evidence_graph_admission"
        )


class TaskOutlineProfileRead(ORMModel):
    id: str
    normalized_ref_id: str
    asset_version_id: str
    asset_profile: str
    title: str | None
    textbook_subtype: str | None
    task_profile: str | None
    subtype_confidence: Decimal | None
    processing_profile: str
    evidence_graph_admission: str
    source_block_ids: list[str]
    quality: dict[str, Any]
    profile_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TaskOutlineNodeCreate(BaseModel):
    id: str | None = Field(default=None, max_length=36)
    normalized_ref_id: str = Field(min_length=1, max_length=36)
    profile_id: str | None = Field(default=None, max_length=36)
    parent_id: str | None = Field(default=None, max_length=36)
    node_type: str = Field(min_length=1, max_length=64)
    section_type: str | None = Field(default=None, max_length=64)
    title: str | None = None
    content: str | None = None
    summary: str | None = None
    order_no: int = Field(default=0, ge=0)
    depth: int = Field(default=0, ge=0)
    source_block_ids: list[str] = Field(default_factory=list)
    locator: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("node_type")
    @classmethod
    def validate_node_type(cls, value: str) -> str:
        return _validate_required_choice(value, NODE_TYPES, "node_type")

    @field_validator("section_type")
    @classmethod
    def validate_section_type(cls, value: str | None) -> str | None:
        return _validate_optional_choice(value, SECTION_TYPES, "section_type")


class TaskOutlineNodeRead(ORMModel):
    id: str
    normalized_ref_id: str
    profile_id: str
    parent_id: str | None
    node_type: str
    section_type: str | None
    title: str | None
    content: str | None
    summary: str | None
    order_no: int
    depth: int
    source_block_ids: list[str]
    locator: dict[str, Any] | None
    node_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


def _validate_optional_choice(
    value: str | None,
    allowed: set[str],
    field_name: str,
) -> str | None:
    if value is None:
        return None
    return _validate_required_choice(value, allowed, field_name)


def _validate_required_choice(value: str, allowed: set[str], field_name: str) -> str:
    stripped = value.strip()
    if stripped not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise ValueError(f"{field_name} must be one of: {allowed_values}")
    return stripped

