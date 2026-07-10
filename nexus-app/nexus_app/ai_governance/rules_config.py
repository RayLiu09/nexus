"""Pydantic models mapping governance_rules.json structure."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ClassificationCoEmissionRule(BaseModel):
    """A co-emission rule attached to a classification (NOT to a KT) — drives
    secondary knowledge-type emissions when the primary KT is selected."""

    target_code: str
    condition: str
    min_confidence: float = Field(default=0.6, ge=0, le=1)

    model_config = {"extra": "ignore"}


class ClassificationDef(BaseModel):
    code: str
    name: str
    description: str = ""
    criteria: list[str] = []
    examples: list[str] = []
    # v3.0+ business-rules fields (governance_rules_v2.json §12):
    primary_knowledge_type: str | None = None
    default_level: str | None = None
    co_emission_rules: list[ClassificationCoEmissionRule] = Field(default_factory=list)

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


# ---------------------------------------------------------------------------
# tag_taxonomy — cross-asset retrieval-side tag type skeleton (v1.3 §4.4)
# ---------------------------------------------------------------------------


TagTypeCode = Literal[
    "region", "industry", "occupation", "major", "ability", "topic", "time_range"
]
TagTypeCardinality = Literal["low", "medium", "high"]


class TagTaxonomyType(BaseModel):
    code: TagTypeCode
    name: str
    description: str = ""
    canonical_source: str | None = None
    allow_free_form: bool = True
    expected_cardinality: TagTypeCardinality = "medium"

    model_config = {"extra": "ignore"}


class TagTaxonomyConfig(BaseModel):
    version: str = "1.0"
    types: list[TagTaxonomyType] = Field(min_length=1)
    auto_accept_threshold: float = Field(default=0.75, ge=0, le=1)
    review_threshold: float = Field(default=0.55, ge=0, le=1)
    notes: str = ""

    model_config = {"extra": "ignore"}

    @model_validator(mode="after")
    def check_type_codes_unique(self) -> "TagTaxonomyConfig":
        codes = [t.code for t in self.types]
        if len(codes) != len(set(codes)):
            raise ValueError("tag_taxonomy.types codes must be unique")
        return self

    @model_validator(mode="after")
    def check_thresholds(self) -> "TagTaxonomyConfig":
        if self.review_threshold >= self.auto_accept_threshold:
            raise ValueError(
                "tag_taxonomy.review_threshold must be < auto_accept_threshold"
            )
        return self


class GovernanceRulesConfig(BaseModel):
    schema_version: str
    classifications: list[ClassificationDef] = Field(min_length=1)
    levels: list[LevelDef] = Field(min_length=1)
    tags: list[TagDef] = Field(default_factory=list)
    quality_scoring: QualityScoringConfig
    manual_review_triggers: list[ManualReviewTriggerDef] = Field(default_factory=list)
    approved_private_model_aliases: list[str] = Field(default_factory=list)
    tag_dimensions: dict = Field(default_factory=dict)
    tag_taxonomy: TagTaxonomyConfig | None = None

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
