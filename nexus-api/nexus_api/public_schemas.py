"""Typed public Agent consumption contracts; free-form objects are source evidence only."""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MarketJobSourceFields(BaseModel):
    title_raw: str
    company_name_raw: str | None
    address_raw: str | None
    salary_raw: str | None
    experience_raw: str | None
    degree_raw: str | None
    hiring_raw: str | None
    description_raw: str | None
    skills_raw: str | None
    job_tags_raw: str | None
    responsibilities_raw: str | None
    requirements_raw: str | None
    qualifications_raw: str | None
    other_matters_raw: str | None
    company_industry_raw: str | None
    company_scale_raw: str | None
    company_financing_raw: str | None


class MarketJobRead(BaseModel):
    id: str
    job_title: str
    job_responsibilities: str | None
    experience_requirement: str | None
    education: str | None
    salary_range: str | None
    industry: str | None
    company_name: str | None
    company_size: str | None
    address: str | None
    source_url: str | None
    collected_at: datetime | None
    created_at: datetime | None
    provider_code: str | None
    upstream_record_id: str | None
    source_type: Literal["raw_jobs"] = "raw_jobs"
    raw_fields: MarketJobSourceFields
    source_name: str | None
    source_job_id: str | None
    received_at: datetime | None


class MarketJobGroup(BaseModel):
    dimensions: dict[str, str | None]
    record_count: int


class ParkRead(BaseModel):
    id: str
    park_name: str
    industry_tags: str
    introduction: str
    enterprise_count: int
    source_url: str | None
    created_at: datetime | None
    updated_at: datetime | None


class EnterpriseRead(BaseModel):
    id: str
    enterprise_name: str
    business_scope: str
    industrial_park_id: str | None
    park_name: str | None
    source_url: str | None
    created_at: datetime | None
    updated_at: datetime | None


class StandardRead(BaseModel):
    id: str
    normalized_ref_id: str
    asset_version_id: str
    raw_object_id: str | None
    standard_title: str | None
    major_code: str | None
    major_name: str | None
    major_category_code: str | None
    major_category_name: str | None
    major_class_code: str | None
    major_class_name: str | None
    educational_level: str | None
    basic_study_years: str | None
    status: Literal["active"]
    course_count: int
    updated_at: datetime | None


class StandardCourseRead(BaseModel):
    id: str
    library_id: str
    course_id: str
    course_name: str
    major_code: str | None
    major_name: str | None
    educational_level: str | None
    library_status: Literal["active"]
    course_type: Literal["foundation", "core", "extension"]
    suggested_total_hours: int | None
    suggested_practice_hours: int | None
    suggested_hours_range: dict[str, Any] | None
    hours_setting_basis: str | None
    typical_work_task_description: str | None
    teaching_content_requirement: str | None
    knowledge_tags: list[str]
    skill_tags: list[str]
    tool_tags: list[str]
    literacy_tags: list[str]
    match_keywords: str | None
    match_text: str | None
    source_standard: str | None
    source_section: str
    source_page: str | None
    source_order: int
    evidence_bindings: list[dict[str, Any]]
    updated_at: datetime | None
    normalized_ref_id: str
    hours_semantics: Literal["suggested"] = "suggested"
    tag_semantics: Literal["derived"] = "derived"


class TextbookRead(BaseModel):
    profile_id: str
    normalized_ref_id: str
    asset_version_id: str
    asset_id: str
    raw_object_id: str
    title: str
    textbook_type: Literal["theory", "training"]
    textbook_type_label: str
    source_subtype: str
    publisher: str | None
    chief_editors: list[str]
    publication_year: int | None
    outline_types: list[Literal["knowledge", "task"]] = Field(default_factory=list)


class ChunkRead(BaseModel):
    id: str
    normalized_ref_id: str
    knowledge_type_code: str
    chunk_type: str
    chunk_index: int
    content: str
    version_id: str
    asset_id: str | None
    locator: dict[str, Any] | None
    source_block_ids: list[str] | None
    primary_block_ids: list[str] | None = None
    evidence_block_ids: list[str] | None = None
    truncated: bool = False
    content_offset: int = 0
    content_total_chars: int | None = None


class SectionRead(BaseModel):
    id: str
    normalized_ref_id: str
    title: str | None = None
    content: str
    source_block_ids: list[str]
    locator: dict[str, Any] = Field(default_factory=dict)
    offset: int
    total_chars: int
    truncated: bool
    next_offset: int | None


class OutlineNodeRead(BaseModel):
    id: str
    parent_id: str | None
    title: str | None
    depth: int
    order: int
    node_type: str
    content: str | None = None
    content_truncated: bool = False
    source_block_ids: list[str] = Field(default_factory=list)
    locator: dict[str, Any] | None = None


class OutlineRead(BaseModel):
    normalized_ref_id: str
    outline_type: Literal["knowledge", "task"]
    available: bool
    nodes: list[OutlineNodeRead]
    total: int
    has_more: bool
    next_offset: int | None


class NodeContextRead(BaseModel):
    normalized_ref_id: str
    node: OutlineNodeRead
    chunks: list[ChunkRead]
    total: int
    next_offset: int | None
    next_char_offset: int = 0
    truncated: bool


class GraphNodeRead(BaseModel):
    id: str
    node_type: str
    name: str
    properties: dict[str, Any]
    confidence: float | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class GraphEdgeRead(BaseModel):
    id: str
    source_node_id: str
    target_node_id: str
    relation_type: str
    confidence: float | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class GraphFactRead(BaseModel):
    id: str
    fact_type: str
    subject_node_id: str
    predicate: str
    object_node_id: str | None
    object_literal: str | None
    qualifiers: dict[str, Any]
    confidence: float | None
    truncated: bool


class GraphRead(BaseModel):
    normalized_ref_id: str
    available: bool
    build_id: str | None = None
    graph_type: str
    nodes: list[GraphNodeRead]
    edges: list[GraphEdgeRead]
    facts: list[GraphFactRead] = Field(default_factory=list)
    truncated: bool
    reason: str | None = None


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["chunk", "normalized_ref", "market_job", "enterprise", "industrial_park", "major_distribution", "ability_item"]
    id: str = Field(min_length=1, max_length=64)


class EvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    references: list[EvidenceReference] = Field(min_length=1, max_length=30)
    max_chars: int = Field(2000, ge=100, le=10000)


class EvidenceResolution(BaseModel):
    kind: str
    id: str
    status: Literal["available", "not_found"]
    content: str | None = None
    normalized_ref_id: str | None = None
    asset_id: str | None = None
    version_id: str | None = None
    source_url: str | None = None
    collected_at: datetime | None = None
    source_block_ids: list[str] = Field(default_factory=list)
    locator: dict[str, Any] | None = None
    truncated: bool = False


class EntityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: Literal["major", "course", "enterprise", "industrial_park"]
    query: str = Field(min_length=1, max_length=256)
    limit: int = Field(10, ge=1, le=30)


class EntityCandidate(BaseModel):
    id: str
    entity_type: str
    name: str
    code: str | None = None
    match_type: Literal["exact", "substring"]
    source_resource: str


class ResourceRead(BaseModel):
    code: str
    name: str
    classification: str | None
    source_type: Literal["document", "record", "projection"]
    count: int
    count_unit: str
    endpoint: str
    capabilities: list[str]
    visibility: str
    limitations: list[str]
    filter_parameters: list[str] = Field(default_factory=list)


class SectionPage(BaseModel):
    items: list[SectionRead]
    total: int
    next_offset: int | None


class AbilityItemRead(BaseModel):
    id: str
    analysis_id: str
    task_id: str
    work_content_id: str | None
    ability_code: str
    ability_major_category_code: str
    ability_major_category_name: str
    ability_sequence: str
    ability_content: str
    normalized_terms: dict[str, Any]
    confidence: float | None
    quality_flags: dict[str, Any]
    trace: dict[str, Any]
    major_code: str | None = None
    major_name: str
    normalized_ref_id: str


class PlanCourseRead(BaseModel):
    id: str
    plan_id: str
    normalized_ref_id: str
    item_index: int
    course_name: str
    course_code: str | None
    curriculum_group: str
    course_type: str
    course_objective: str | None
    course_content: str | None
    skill_refs: list[dict[str, Any]]
    knowledge_topics: list[dict[str, Any]]
    evidence: dict[str, Any]
    confidence: float | None


class SearchHitRead(BaseModel):
    model_config = ConfigDict(extra="allow")
    nexus_chunk_id: str | None = None
    normalized_ref_id: str
    score: float
    content: str | None = None
    snippet: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    knowledge_type_code: str | None = None
    collection_key: str | None = None
    version_id: str | None = None
    asset_id: str | None = None
    data_source_id: str | None = None
    locator: dict[str, Any] | None = None
    source_block_ids: list[str] | None = None
    primary_block_ids: list[str] | None = None
    evidence_block_ids: list[str] | None = None
    knowledge_outline: dict[str, Any] | None = None


class SearchRead(BaseModel):
    query: str
    kb: str
    knowledge_types: list[str]
    results: list[SearchHitRead]
    count: int
    caller_id: str
