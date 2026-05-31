"""Pydantic models for normalize contracts and validation results."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class FormatConstraint(BaseModel):
    pattern: str | None = None
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=1)
    min_items: int | None = Field(default=None, ge=0)
    max_items: int | None = Field(default=None, ge=1)
    description: str | None = None


class NormalizeContract(BaseModel):
    description: str | None = None
    normalized_type: Literal["document", "record"]
    required_fields: list[str] = Field(default_factory=list)
    format_constraints: dict[str, FormatConstraint] = Field(default_factory=dict)
    classification_hint_whitelist: list[str] = Field(default_factory=list)


class NormalizeSchemasFile(BaseModel):
    schema_version: str
    contracts: dict[str, NormalizeContract] = Field(default_factory=dict)
    fallback_contract: NormalizeContract


class NormalizeValidationIssue(BaseModel):
    field: str
    code: str  # e.g. "missing_required", "format_violation", "classification_out_of_whitelist"
    message: str


class NormalizeResult(BaseModel):
    payload: dict[str, Any]
    contract_key: str
    schema_version: str
    llm_used: bool
    llm_fallback_reason: str | None = None
    issues: list[NormalizeValidationIssue] = Field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.issues
