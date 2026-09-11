"""AI output schema validation using Pydantic v2."""
from __future__ import annotations

import logging
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    knowledge_type: str | None = None

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        if v not in {"L1", "L2", "L3", "L4"}:
            raise ValueError(f"level must be L1/L2/L3/L4, got '{v}'")
        return v


class GovernanceStageOutput(BaseModel):
    model_config = ConfigDict(extra="allow")


class ClassificationStageOutput(GovernanceStageOutput):
    classification_code: str
    classification_name: str | None = None
    confidence: float = Field(ge=0, le=1)
    evidence: Any = None


class LevelAssessmentStageOutput(GovernanceStageOutput):
    level_code: Literal["L1", "L2", "L3", "L4"]
    level_name: str | None = None
    confidence: float = Field(ge=0, le=1)
    evidence: Any = None
    sensitive_fields: list[str] = Field(default_factory=list)


class TaggingStageOutput(GovernanceStageOutput):
    tags: dict[str, list[Any]]
    confidence: float = Field(ge=0, le=1)


class QualityDimensionOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    score: float = Field(ge=0, le=100)
    weight: float = Field(ge=0)
    comment: str | None = None


class QualityAssessmentStageOutput(GovernanceStageOutput):
    dimensions: list[QualityDimensionOutput] = Field(default_factory=list)
    overall_score: float = Field(ge=0, le=100)
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class KnowledgeTypeCandidateOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str
    name: str | None = None
    confidence: float = Field(ge=0, le=1)
    rationale: str | None = None


class KnowledgeInferenceStageOutput(GovernanceStageOutput):
    knowledge_types: list[KnowledgeTypeCandidateOutput] = Field(default_factory=list)
    primary_type: str | None = None


_STAGE_MODELS: dict[str, type[GovernanceStageOutput]] = {
    "classification": ClassificationStageOutput,
    "level_assessment": LevelAssessmentStageOutput,
    "tagging": TaggingStageOutput,
    "quality_scoring": QualityAssessmentStageOutput,
    "quality_assessment": QualityAssessmentStageOutput,
    "knowledge_type_inference": KnowledgeInferenceStageOutput,
    "knowledge_inference": KnowledgeInferenceStageOutput,
}


def validate_governance_stage_output(
    task_type: str,
    payload: dict[str, Any],
    *,
    registry: Any | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate one governance stage against its fixed runtime contract."""
    model = _STAGE_MODELS.get(task_type)
    if model is None:
        return None, f"unsupported governance task_type '{task_type}'"
    try:
        output = model.model_validate(payload)
    except Exception as exc:
        return None, f"Schema validation error: {exc}"

    if registry is not None and isinstance(output, ClassificationStageOutput):
        valid_codes = {item.code for item in registry.get_classifications()}
        if output.classification_code not in valid_codes:
            return None, (
                f"classification '{output.classification_code}' is not in "
                f"registry-defined classifications {sorted(valid_codes)}"
            )
    if registry is not None and isinstance(output, KnowledgeInferenceStageOutput):
        valid_codes = {
            str(item.get("code")) for item in registry.get_knowledge_types()
            if item.get("code")
        }
        emitted = {item.code for item in output.knowledge_types}
        if output.primary_type:
            emitted.add(output.primary_type)
        invalid = sorted(emitted - valid_codes)
        if invalid:
            return None, f"knowledge type codes are not active: {invalid}"

    return output.model_dump(), None


class AIOutputValidator(Protocol):
    def validate(self, raw_output: str) -> tuple[AIGovernanceOutput | None, str | None]: ...


class PydanticOutputValidator:
    """Validates AI raw JSON output against AIGovernanceOutput schema.

    When a GovernanceRulesRegistry is provided, validates classification
    against the registry-defined valid set. Tags are free-form values under
    fixed dimensions, so they are schema-checked but not whitelist-checked.
    """

    def __init__(self, registry: Any | None = None) -> None:
        self._registry = registry

    def validate(self, raw_output: str) -> tuple[AIGovernanceOutput | None, str | None]:
        import json
        try:
            parsed = json.loads(raw_output)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("AI output is not valid JSON: %s", exc)
            return None, f"JSON parse error: {exc}"

        try:
            output = AIGovernanceOutput.model_validate(parsed)
        except Exception as exc:
            logger.warning("AI output schema validation failed: %s", exc)
            return None, f"Schema validation error: {exc}"

        if self._registry is not None:
            error = self._validate_against_registry(output)
            if error:
                logger.warning("AI output registry validation failed: %s", error)
                return None, error

        return output, None

    def _validate_against_registry(self, output: AIGovernanceOutput) -> str | None:
        """Validate classification and tags against registry-defined valid sets."""
        valid_classifications = {c.code for c in self._registry.get_classifications()}
        if output.classification not in valid_classifications:
            return (
                f"classification '{output.classification}' is not in registry-defined "
                f"classifications {sorted(valid_classifications)}"
            )

        return None
