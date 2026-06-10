"""Pydantic models mapping governance_rules.json structure."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ClassificationDef(BaseModel):
    code: str
    name: str
    description: str = ""
    criteria: list[str] = []
    examples: list[str] = []

    model_config = {"extra": "ignore"}


class LevelDef(BaseModel):
    code: Literal["L1", "L2", "L3", "L4"]
    name: str
    description: str
    criteria: list[str]
    requires_approval: bool = False
    forbid_external_llm: bool = False


class TagDef(BaseModel):
    code: str
    name: str
    description: str
    criteria: list[str]
    applicable_classifications: list[str] = []


class QualityCheckItemDef(BaseModel):
    name: str
    description: str
    severity: Literal["blocking", "warning", "info"]


class QualityDimensionDef(BaseModel):
    name: str
    weight: float = Field(gt=0, le=1)
    description: str
    check_items: list[QualityCheckItemDef]


class QualityThresholds(BaseModel):
    pass_: int = Field(alias="pass", ge=0, le=100)
    warning: int = Field(ge=0, le=100)
    review_required_below: int = Field(default=0, ge=0, le=100)

    model_config = {"populate_by_name": True}


class QualityScoringConfig(BaseModel):
    dimensions: list[QualityDimensionDef]
    thresholds: QualityThresholds
    confidence_threshold_auto_adopt: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def check_weights_sum(self) -> "QualityScoringConfig":
        total = sum(d.weight for d in self.dimensions)
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"dimension weights must sum to 1.0, got {total:.4f}")
        return self


class ManualReviewTriggerDef(BaseModel):
    code: str
    name: str
    description: str
    condition: str


class GovernanceRulesConfig(BaseModel):
    schema_version: str
    classifications: list[ClassificationDef] = Field(min_length=1)
    levels: list[LevelDef] = Field(min_length=1)
    tags: list[TagDef] = Field(default_factory=list)
    quality_scoring: QualityScoringConfig
    manual_review_triggers: list[ManualReviewTriggerDef] = Field(default_factory=list)
    approved_private_model_aliases: list[str] = Field(default_factory=list)
    tag_dimensions: dict = Field(default_factory=dict)

    model_config = {"extra": "ignore"}

    @model_validator(mode="after")
    def check_tag_classification_refs(self) -> "GovernanceRulesConfig":
        valid_codes = {c.code for c in self.classifications}
        for tag in self.tags:
            for ref in tag.applicable_classifications:
                if ref not in valid_codes:
                    raise ValueError(
                        f"tag '{tag.code}' references unknown classification '{ref}'"
                    )
        return self

    @model_validator(mode="after")
    def check_level_codes(self) -> "GovernanceRulesConfig":
        valid = {"L1", "L2", "L3", "L4"}
        for level in self.levels:
            if level.code not in valid:
                raise ValueError(f"invalid level code '{level.code}', must be one of {valid}")
        return self
