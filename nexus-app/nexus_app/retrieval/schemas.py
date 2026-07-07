"""Pydantic contracts for v1.0 retrieval/recall orchestration.

These models describe runtime/API payloads only. They do not imply persistence
of user query text, answer text, prompt text, or source content in audit logs.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

INTENT_CONFIDENCE_THRESHOLD = 0.78
MAX_SUB_QUERIES = 5
ACCESS_SCOPE_ALL_ASSETS = "all_assets"


class BusinessDomain(StrEnum):
    COURSE_TEXTBOOK = "course_textbook"
    MAJOR_PROFILE = "major_profile"
    MAJOR_DISTRIBUTION = "major_distribution"
    JOB_DEMAND = "job_demand"
    COMPETENCY_ANALYSIS = "competency_analysis"


class RetrievalChannel(StrEnum):
    UNSTRUCTURED = "unstructured"
    STRUCTURED = "structured"
    HYBRID = "hybrid"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    NEEDS_CLARIFICATION = "needs_clarification"
    BLOCKED = "blocked"
    FAILED = "failed"
    SKIPPED = "skipped"


class ConversationStepName(StrEnum):
    INTENT_RECOGNITION = "intent_recognition"
    CLARIFICATION = "clarification"
    QUERY_TRANSFORMATION = "query_transformation"
    PARALLEL_RETRIEVAL = "parallel_retrieval"
    CONTEXT_ASSEMBLY = "context_assembly"
    SUMMARY_GENERATION = "summary_generation"


class ContextPackStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    NEEDS_CLARIFICATION = "needs_clarification"
    PARTIAL = "partial"
    FAILED = "failed"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class CandidateIntent(StrictModel):
    business_domain: BusinessDomain
    question_type: str
    confidence: float = Field(ge=0.0, le=1.0)


class RetrievalIntent(StrictModel):
    business_domains: list[BusinessDomain] = Field(min_length=1)
    retrieval_channels: list[RetrievalChannel] = Field(min_length=1)
    question_type: str = Field(min_length=1)
    output_expectation: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_threshold: float = Field(default=INTENT_CONFIDENCE_THRESHOLD, ge=0.0, le=1.0)
    candidate_intents: list[CandidateIntent] = Field(default_factory=list)
    missing_constraints: list[str] = Field(default_factory=list)
    suggested_refinements: list[str] = Field(default_factory=list)
    clarification_policy: str = "ask_user_when_confidence_below_0_78"

    @property
    def needs_clarification(self) -> bool:
        return self.confidence < self.confidence_threshold

    @field_validator("output_expectation", "missing_constraints", "suggested_refinements")
    @classmethod
    def _dedupe_strings(cls, values: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for value in values:
            stripped = str(value).strip()
            if stripped and stripped not in seen:
                seen.add(stripped)
                out.append(stripped)
        return out


class QueryMetric(StrictModel):
    field: str = Field(min_length=1)
    function: str = Field(min_length=1)
    alias: str | None = None


class QueryOrder(StrictModel):
    field: str = Field(min_length=1)
    direction: str = Field(default="asc", pattern="^(asc|desc)$")


class StructuredPlan(StrictModel):
    table_profile: str = Field(min_length=1)
    query_profile: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    group_by: list[str] = Field(default_factory=list)
    metrics: list[QueryMetric] = Field(default_factory=list)
    order_by: list[QueryOrder] = Field(default_factory=list)
    limit: int = Field(default=50, ge=1, le=200)


class UnstructuredPlan(StrictModel):
    top_k: int = Field(default=8, ge=1, le=100)
    filters: dict[str, Any] = Field(default_factory=dict)
    query_terms: list[str] = Field(default_factory=list)
    similarity_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class RetrievalSubQuery(StrictModel):
    query_id: str = Field(min_length=1)
    channel: RetrievalChannel
    domain: BusinessDomain
    purpose: str = Field(min_length=1)
    query_text: str = Field(min_length=1)
    structured_plan: StructuredPlan | None = None
    unstructured_plan: UnstructuredPlan | None = None

    @model_validator(mode="after")
    def _validate_plan_for_channel(self):
        if self.channel == RetrievalChannel.STRUCTURED and self.structured_plan is None:
            raise ValueError("structured sub query requires structured_plan")
        if self.channel == RetrievalChannel.UNSTRUCTURED and self.unstructured_plan is None:
            raise ValueError("unstructured sub query requires unstructured_plan")
        if self.channel == RetrievalChannel.HYBRID:
            if self.structured_plan is None and self.unstructured_plan is None:
                raise ValueError("hybrid sub query requires at least one plan")
        return self


class RetrievalPlan(StrictModel):
    original_query: str = Field(min_length=1)
    sub_queries: list[RetrievalSubQuery] = Field(min_length=1, max_length=MAX_SUB_QUERIES)
    merge_goal: str = Field(default="生成结构化 Markdown 检索/召回结果")

    @model_validator(mode="after")
    def _validate_unique_query_ids(self):
        query_ids = [sub_query.query_id for sub_query in self.sub_queries]
        if len(query_ids) != len(set(query_ids)):
            raise ValueError("sub query ids must be unique")
        return self


class RetrievalSourceRef(StrictModel):
    source_ref_id: str = Field(default_factory=lambda: f"src-{uuid4().hex[:12]}")
    channel: RetrievalChannel
    domain: BusinessDomain
    asset_id: str | None = None
    asset_version_id: str | None = None
    normalized_ref_id: str | None = None
    chunk_id: str | None = None
    record_ref: str | None = None
    locator: dict[str, Any] = Field(default_factory=dict)
    score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UnstructuredResultItem(StrictModel):
    result_id: str
    chunk_id: str
    normalized_ref_id: str
    asset_id: str | None = None
    asset_version_id: str | None = None
    score: float | None = None
    content_preview: str = ""
    snippet: str | None = None
    match_reason: list[str] = Field(default_factory=list)
    locator: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_ref_id: str | None = None


class StructuredAggregation(StrictModel):
    group_by: list[str] = Field(default_factory=list)
    metric: str
    series: list[dict[str, Any]] = Field(default_factory=list)


class RetrievalResult(StrictModel):
    query_id: str
    channel: RetrievalChannel
    domain: BusinessDomain
    status: StepStatus = StepStatus.COMPLETED
    result_shape: str | None = None
    items: list[UnstructuredResultItem] = Field(default_factory=list)
    records: list[dict[str, Any]] = Field(default_factory=list)
    aggregations: list[StructuredAggregation] = Field(default_factory=list)
    source_refs: list[RetrievalSourceRef] = Field(default_factory=list)
    elapsed_ms: float | None = Field(default=None, ge=0.0)
    error_message: str | None = None


class Clarification(StrictModel):
    message: str
    suggested_refinements: list[str] = Field(default_factory=list)
    candidate_intents: list[CandidateIntent] = Field(default_factory=list)
    missing_constraints: list[str] = Field(default_factory=list)


class ConversationStep(StrictModel):
    step: ConversationStepName
    status: StepStatus
    title: str
    display_to_user: bool = True
    message: str | None = None
    progress: dict[str, Any] = Field(default_factory=dict)
    display_payload: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class LlmSummary(StrictModel):
    format: str = "markdown"
    content: str
    source_ref_ids: list[str] = Field(default_factory=list)
    model_alias: str | None = None
    warnings: list[str] = Field(default_factory=list)


class RetrievalContextPack(StrictModel):
    query_id: str = Field(default_factory=lambda: f"query-{uuid4().hex}")
    status: ContextPackStatus
    original_query: str
    intent: RetrievalIntent
    retrieval_plan: RetrievalPlan | None = None
    retrieval_results: list[RetrievalResult] = Field(default_factory=list)
    llm_summary: LlmSummary | None = None
    access_scope: str = ACCESS_SCOPE_ALL_ASSETS
    conversation_steps: list[ConversationStep] = Field(default_factory=list)
    source_refs: list[RetrievalSourceRef] = Field(default_factory=list)
    clarification: Clarification | None = None
    warnings: list[str] = Field(default_factory=list)

    @field_validator("access_scope")
    @classmethod
    def _access_scope_all_assets_only(cls, value: str) -> str:
        if value != ACCESS_SCOPE_ALL_ASSETS:
            raise ValueError("v1.0 retrieval context pack only supports access_scope=all_assets")
        return value

    @model_validator(mode="after")
    def _validate_clarification_shape(self):
        if self.status == ContextPackStatus.NEEDS_CLARIFICATION and self.clarification is None:
            raise ValueError("needs_clarification context pack requires clarification")
        return self

