"""Intermediate schemas for Evidence-grounded KG extraction."""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GraphExtractionRejectReason(StrEnum):
    SCHEMA_INVALID = "schema_invalid"
    LANGUAGE_MISMATCH = "language_mismatch"
    LLM_CLIENT_UNAVAILABLE = "llm_client_unavailable"
    LLM_CALL_FAILED = "llm_call_failed"
    UNSUPPORTED_EXTRACTOR = "unsupported_extractor"
    NO_FACT_CANDIDATE = "no_fact_candidate"
    BODY_REQUIRES_LLM = "body_requires_llm"


class GraphEntityRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=512)

    @field_validator("type", "name")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class GraphFactCandidate(BaseModel):
    """Validated chunk-level fact candidate.

    This is an intermediate object. It is not written directly to graph tables;
    Task Package D owns merge, normalization, quality gates, and persistence.
    """

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(default_factory=lambda: str(uuid4()))
    source_chunk_id: str = Field(min_length=1)
    profile: str = Field(min_length=1, max_length=64)
    anchor_role: str = Field(min_length=1, max_length=64)
    extractor_name: str = Field(min_length=1, max_length=128)
    extraction_method: str = Field(min_length=1, max_length=32)
    fact_type: str = Field(min_length=1, max_length=64)
    subject: GraphEntityRef
    predicate: str = Field(min_length=1, max_length=128)
    object: GraphEntityRef | None = None
    object_literal: str | None = Field(default=None, max_length=2048)
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    evidence_text: str = Field(min_length=1, max_length=4096)
    confidence: float = Field(ge=0, le=1)

    @field_validator(
        "source_chunk_id",
        "profile",
        "anchor_role",
        "extractor_name",
        "extraction_method",
        "fact_type",
        "predicate",
        "evidence_text",
    )
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("object_literal")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def object_or_literal_required(self) -> "GraphFactCandidate":
        if self.object is None and not self.object_literal:
            raise ValueError("object or object_literal is required")
        return self


class GraphExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_chunk_id: str
    extractor_name: str
    extraction_method: str
    accepted: list[GraphFactCandidate] = Field(default_factory=list)
    rejected_count: int = 0
    reject_reasons: dict[str, int] = Field(default_factory=dict)
    reject_samples: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def accepted_count(self) -> int:
        return len(self.accepted)


def rejected_result(
    *,
    source_chunk_id: str,
    extractor_name: str,
    extraction_method: str,
    reason: str,
    count: int = 1,
) -> GraphExtractionResult:
    return GraphExtractionResult(
        source_chunk_id=source_chunk_id,
        extractor_name=extractor_name,
        extraction_method=extraction_method,
        rejected_count=count,
        reject_reasons={reason: count},
    )


def aggregate_extraction_results(
    results: list[GraphExtractionResult],
) -> dict[str, int]:
    summary: dict[str, int] = {
        "accepted_candidates": 0,
        "rejected_candidates": 0,
    }
    for result in results:
        summary["accepted_candidates"] += result.accepted_count
        summary["rejected_candidates"] += result.rejected_count
        for reason, count in result.reject_reasons.items():
            key = f"reject_{reason}"
            summary[key] = summary.get(key, 0) + count
    return summary
