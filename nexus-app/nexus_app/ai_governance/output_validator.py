"""AI output schema validation using Pydantic v2."""
from __future__ import annotations

import logging
from typing import Any, Protocol

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class AIGovernanceError(Exception):
    pass


class SchemaValidationError(AIGovernanceError):
    pass


class EvidenceRef(BaseModel):
    field: str
    value: Any
    confidence: float = Field(ge=0, le=1)
    source_position: dict[str, Any] | None = None


class AIClassificationOutput(BaseModel):
    classification: str
    confidence: float = Field(ge=0, le=1)
    evidence_refs: list[EvidenceRef] = []


class AILevelOutput(BaseModel):
    level: str
    confidence: float = Field(ge=0, le=1)
    evidence_refs: list[EvidenceRef] = []

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        if v not in {"L1", "L2", "L3", "L4"}:
            raise ValueError(f"level must be L1/L2/L3/L4, got '{v}'")
        return v


class AITagOutput(BaseModel):
    tag: str
    confidence: float = Field(ge=0, le=1)
    evidence_refs: list[EvidenceRef] = []


class AIQualityOutput(BaseModel):
    overall_score: float = Field(ge=0, le=100)
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1)
    evidence_refs: list[EvidenceRef] = []
    blocking_reasons: list[str] = []


class AIGovernanceOutput(BaseModel):
    classification: str
    level: str
    tags: list[str] = []
    org_scope: str = "all"
    quality_scores: dict[str, float] = Field(default_factory=dict)
    overall_score: float = Field(ge=0, le=100)
    evidence_refs: list[EvidenceRef] = []
    confidence: float = Field(ge=0, le=1)
    reasoning: str = ""

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        if v not in {"L1", "L2", "L3", "L4"}:
            raise ValueError(f"level must be L1/L2/L3/L4, got '{v}'")
        return v


class AIOutputValidator(Protocol):
    def validate(self, raw_output: str) -> tuple[AIGovernanceOutput | None, str | None]: ...


class PydanticOutputValidator:
    """Validates AI raw JSON output against AIGovernanceOutput schema."""

    def validate(self, raw_output: str) -> tuple[AIGovernanceOutput | None, str | None]:
        import json
        try:
            parsed = json.loads(raw_output)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("AI output is not valid JSON: %s", exc)
            return None, f"JSON parse error: {exc}"

        try:
            output = AIGovernanceOutput.model_validate(parsed)
            return output, None
        except Exception as exc:
            logger.warning("AI output schema validation failed: %s", exc)
            return None, f"Schema validation error: {exc}"
