from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nexus_app.enums import (
    AIGovernanceRunAdoptionStatus,
    AIGovernanceRunValidationStatus,
    AssetKind,
    AssetVersionStatus,
    DataSourceStatus,
    DataSourceType,
    IngestBatchStatus,
    JobStatus,
    JobType,
    NormalizedAssetRefStatus,
    NormalizedType,
    OrgUnitStatus,
    ParseArtifactStatus,
    PrincipalStatus,
    PromptProfileStatus,
    RawObjectStatus,
    StageStatus,
    UserRole,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class OrgUnitCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    parent_id: str | None = None
    status: OrgUnitStatus = OrgUnitStatus.ACTIVE


class OrgUnitRead(ORMModel):
    id: str
    code: str
    name: str
    parent_id: str | None
    status: OrgUnitStatus
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    role: UserRole
    org_unit_id: str | None = None
    email: str | None = Field(default=None, max_length=255)
    status: PrincipalStatus = PrincipalStatus.ACTIVE


class UserRead(ORMModel):
    id: str
    username: str
    display_name: str
    role: UserRole
    org_unit_id: str | None
    email: str | None
    status: PrincipalStatus
    created_at: datetime
    updated_at: datetime


class ApiCallerCreate(BaseModel):
    """Request body for POST /v1/api-callers.

    `caller_key` is OPTIONAL: when omitted, the server mints a fresh key and
    stores only its sha256 digest. Supplying `caller_key` is supported for
    legacy seed scripts and tests but is discouraged for human callers.
    """
    caller_key: str | None = Field(default=None, min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=128)
    org_scope: list[str] = Field(default_factory=list)
    permission_scope: list[str] = Field(default_factory=list)
    owner_user_id: str | None = None
    expired_at: datetime | None = None


class ApiCallerRead(ORMModel):
    id: str
    # Legacy plaintext slot; NULL for server-minted callers (only the hash is stored).
    caller_key: str | None
    name: str
    org_scope: list[str]
    permission_scope: list[str]
    owner_user_id: str | None
    expired_at: datetime | None
    revoked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ApiCallerMintRead(ApiCallerRead):
    """Returned by POST /v1/api-callers for newly server-minted callers.

    `caller_key_plaintext` is the only place this secret is ever surfaced.
    The client must persist it client-side; subsequent reads return None.
    """
    caller_key_plaintext: str | None = None


class NasConnectionConfig(BaseModel):
    """NAS source connection configuration."""
    mount_path: str = Field(min_length=1, max_length=512)
    scan_pattern: str | None = Field(default=None, max_length=256)


class CrawlerConnectionConfig(BaseModel):
    """Crawler source connection configuration."""
    target_url: str = Field(min_length=1, max_length=1024)
    schedule_cron: str | None = Field(default=None, max_length=128)
    auth_token: str | None = Field(default=None, max_length=512)


class DatabaseConnectionConfig(BaseModel):
    """Database source connection configuration."""
    connection_string: str = Field(min_length=1, max_length=1024)
    query: str | None = Field(default=None)
    schedule_cron: str | None = Field(default=None, max_length=128)


class WebhookConnectionConfig(BaseModel):
    """Webhook source connection configuration."""
    webhook_secret: str = Field(min_length=1, max_length=256)
    allowed_ips: list[str] = Field(default_factory=list)


class GovernanceHints(BaseModel):
    """Default governance hints for a data source."""
    sensitivity_level: str | None = Field(default=None, max_length=20)
    quality_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    auto_approve_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    required_reviewers: list[str] = Field(default_factory=list)


class RawObjectMetadataFile(BaseModel):
    """Metadata for file_upload/nas raw objects."""
    filename: str


class RawObjectMetadataCrawler(BaseModel):
    """Metadata for crawler raw objects."""
    package_id: str
    source_url: str | None = None


class RawObjectMetadataDatabase(BaseModel):
    """Metadata for database raw objects."""
    table_name: str | None = None
    record_count: int | None = None


class DataSourceCreate(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=128)
    source_type: DataSourceType
    owner_user_id: str | None = None
    org_scope_hint: list[str] = Field(default_factory=list)
    default_governance_hints: dict[str, Any] = Field(default_factory=dict)
    connection_config: dict[str, Any] | None = None
    description: str | None = None
    status: DataSourceStatus = DataSourceStatus.ENABLED

    @model_validator(mode="after")
    def enforce_default_level_policy(self) -> "DataSourceCreate":
        """Imported data sources default to L1/L2 unless explicit approval is recorded.

        Rule (CLAUDE.md §"P0 imported data sources default to L1/L2"):
          - default_governance_hints.level absent or in {L1, L2}: allowed.
          - level in {L3, L4}: must carry non-empty approval_evidence (free-form
            dict with at least {approver, approved_at, reason} or a non-empty
            string). Audit log additionally records the elevation.
        """
        hints = self.default_governance_hints or {}
        level = hints.get("level")
        if level is None:
            return self
        if level not in {"L1", "L2", "L3", "L4"}:
            raise ValueError(
                f"default_governance_hints.level must be one of L1/L2/L3/L4, got '{level}'"
            )
        if level in {"L3", "L4"}:
            evidence = hints.get("approval_evidence")
            if not evidence:
                raise ValueError(
                    f"default_governance_hints.level={level} requires non-empty "
                    "approval_evidence (e.g. {'approver': ..., 'approved_at': ..., 'reason': ...})"
                )
        return self


class DataSourceRead(ORMModel):
    id: str
    code: str
    name: str
    source_type: DataSourceType
    status: DataSourceStatus
    owner_user_id: str | None
    org_scope_hint: list[str]
    default_governance_hints: dict[str, Any]
    connection_config: dict[str, Any] | None
    description: str | None
    created_at: datetime
    updated_at: datetime


class IngestBatchCreate(BaseModel):
    data_source_id: str
    idempotency_key: str = Field(min_length=1, max_length=128)
    source_type: DataSourceType
    owner_user_id: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    status: IngestBatchStatus = IngestBatchStatus.SUBMITTED


class IngestBatchRead(ORMModel):
    id: str
    data_source_id: str
    idempotency_key: str
    source_type: DataSourceType
    status: IngestBatchStatus
    owner_user_id: str | None
    summary: dict[str, Any]
    batch_status_detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class MultiRawBatchCreate(BaseModel):
    """Two-step API: create empty batch in `open` state, then append files."""

    data_source_id: str
    batch_idempotency_key: str = Field(min_length=1, max_length=128)
    owner_user_id: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


class IngestFileAppend(BaseModel):
    file_idempotency_key: str = Field(min_length=1, max_length=128)
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1)
    content_type: str = Field(default="application/octet-stream", max_length=128)
    source_uri: str | None = Field(default=None, max_length=1024)


class RawObjectCreate(BaseModel):
    batch_id: str
    data_source_id: str
    source_type: DataSourceType
    object_uri: str = Field(min_length=1, max_length=1024)
    checksum: str = Field(min_length=1, max_length=128)
    source_uri: str | None = Field(default=None, max_length=1024)
    mime_type: str | None = Field(default=None, max_length=128)
    size_bytes: int | None = Field(default=None, ge=0)
    metadata_summary: dict[str, Any] = Field(default_factory=dict)
    status: RawObjectStatus = RawObjectStatus.RAW_PERSISTED


class RawObjectRead(ORMModel):
    id: str
    batch_id: str
    data_source_id: str
    source_type: DataSourceType
    source_uri: str | None
    object_uri: str
    checksum: str
    mime_type: str | None
    size_bytes: int | None
    status: RawObjectStatus
    file_idempotency_key: str | None = None
    metadata_summary: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class IngestFileAppendRead(BaseModel):
    raw_object_id: str
    job_id: str
    job_status: JobStatus
    file_idempotency_key: str
    duplicate: bool = False


class IngestMultiFileItem(BaseModel):
    file_idempotency_key: str = Field(min_length=1, max_length=128)
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1)
    content_type: str = Field(default="application/octet-stream", max_length=128)
    source_uri: str | None = Field(default=None, max_length=1024)


class IngestMultiFileSubmit(BaseModel):
    data_source_id: str
    batch_idempotency_key: str = Field(min_length=1, max_length=128)
    owner_user_id: str | None = None
    files: list[IngestMultiFileItem] = Field(min_length=1)


class IngestMultiFileResult(BaseModel):
    batch: IngestBatchRead
    items: list[IngestFileAppendRead]


class AuditLogRead(ORMModel):
    id: str
    event_type: str
    actor_type: str | None
    actor_id: str | None
    target_type: str
    target_id: str
    trace_id: str | None
    summary: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class JobStageRead(ORMModel):
    id: str
    job_id: str
    stage_name: str
    status: StageStatus
    started_at: datetime | None
    finished_at: datetime | None
    failure_reason: str | None
    detail: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class JobRead(ORMModel):
    id: str
    job_type: JobType
    status: JobStatus
    priority: int
    ingest_batch_id: str | None
    raw_object_id: str | None
    idempotency_key: str | None
    next_run_at: datetime
    locked_by: str | None
    attempt_count: int
    max_attempts: int
    retry_count: int
    current_stage: str | None
    failure_reason: str | None
    last_error_code: str | None
    last_error_message: str | None
    trace_id: str | None
    payload: dict[str, Any]
    metadata_summary: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ParseArtifactRead(ORMModel):
    id: str
    raw_object_id: str
    document_version_id: str | None
    artifact_uri: str
    parse_mode: str
    checksum: str
    status: ParseArtifactStatus
    error: str | None
    metadata_summary: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DocumentAssetRead(ORMModel):
    id: str
    data_source_id: str
    source_object_key: str
    title: str
    asset_kind: AssetKind
    status: AssetVersionStatus
    org_scope: list[str]
    metadata_summary: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DocumentVersionRead(ORMModel):
    id: str
    asset_id: str
    raw_object_id: str
    version_no: int
    version_status: AssetVersionStatus
    source_checksum: str
    failure_reason: str | None
    metadata_summary: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class NormalizedAssetRefRead(ORMModel):
    id: str
    version_id: str
    normalized_type: NormalizedType
    object_uri: str
    schema_version: str
    checksum: str
    status: NormalizedAssetRefStatus
    block_count: int
    record_count: int
    metadata_summary: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AssetDetailRead(BaseModel):
    asset: DocumentAssetRead
    versions: list[DocumentVersionRead]
    normalized_refs: list[NormalizedAssetRefRead]
    current_version: DocumentVersionRead | None = None
    current_normalized_ref: NormalizedAssetRefRead | None = None


class IngestFileSubmit(BaseModel):
    data_source_id: str
    idempotency_key: str = Field(min_length=1, max_length=128)
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1)
    content_type: str = Field(default="application/octet-stream", max_length=128)
    source_uri: str | None = Field(default=None, max_length=1024)
    owner_user_id: str | None = None


class CrawlerPackageSubmit(BaseModel):
    data_source_id: str
    idempotency_key: str = Field(min_length=1, max_length=128)
    package: dict[str, Any]
    source_uri: str | None = Field(default=None, max_length=1024)
    owner_user_id: str | None = None


class IngestAcceptedRead(BaseModel):
    batch: IngestBatchRead
    raw_object: RawObjectRead
    job: JobRead


class IngestToAssetResultRead(BaseModel):
    batch: IngestBatchRead
    raw_object: RawObjectRead
    job: JobRead
    asset: DocumentAssetRead | None = None
    version: DocumentVersionRead | None = None
    parse_artifact: ParseArtifactRead | None = None
    normalized_ref: NormalizedAssetRefRead | None = None


class RuntimeStateRead(BaseModel):
    api: str
    database: str
    workers: str
    queue: str
    recent_error: str | None = None


# AI Governance schemas

class PromptProfileCreate(BaseModel):
    profile_name: str = Field(min_length=1, max_length=128)
    task_type: str = Field(min_length=1, max_length=80)
    scenario: str = Field(default="default", min_length=1, max_length=80)
    litellm_model_alias: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(min_length=1, max_length=40)
    prompt_template: str = Field(min_length=1)
    output_schema_version: str = "1.0"
    scoring_weight_version: str = "1.0"
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_input_tokens: int = Field(default=4096, gt=0)
    redaction_policy: str = Field(default="masked_content",
                                   pattern="^(metadata_only|masked_content|full_content_private)$")


class PromptProfileUpdate(BaseModel):
    scenario: str | None = Field(default=None, min_length=1, max_length=80)
    litellm_model_alias: str | None = Field(default=None, max_length=128)
    prompt_version: str | None = Field(default=None, max_length=40)
    prompt_template: str | None = None
    output_schema_version: str | None = None
    scoring_weight_version: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_input_tokens: int | None = Field(default=None, gt=0)
    redaction_policy: str | None = Field(
        default=None,
        pattern="^(metadata_only|masked_content|full_content_private)$",
    )


class PromptProfileRead(ORMModel):
    id: str
    profile_name: str
    profile_version: int
    task_type: str
    scenario: str
    status: PromptProfileStatus
    litellm_model_alias: str
    prompt_version: str
    output_schema_version: str
    scoring_weight_version: str
    temperature: float
    max_input_tokens: int
    redaction_policy: str
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class AIGovernanceRunCreate(BaseModel):
    normalized_ref_id: str
    profile_id: str


class PromptDryRunCreate(BaseModel):
    normalized_ref_id: str
    input_overrides: dict[str, Any] = Field(default_factory=dict)


class PromptDryRunRead(BaseModel):
    profile_id: str
    profile_name: str
    profile_version: int
    scenario: str
    normalized_ref_id: str
    model_alias: str
    prompt_version: str
    input_hash: str
    input_summary: dict[str, Any]
    validation_status: AIGovernanceRunValidationStatus
    adoption_status: AIGovernanceRunAdoptionStatus
    ai_output: dict[str, Any] | None = None
    quality_summary: dict[str, Any] | None = None
    validation_error: str | None = None
    call_latency_ms: float | None = None
    request_id: str | None = None
    persisted: bool = False


class DataSourceScanItem(BaseModel):
    item_id: str | None = Field(default=None, max_length=128)
    source_object_key: str | None = Field(default=None, max_length=512)
    source_uri: str | None = Field(default=None, max_length=1024)
    filename: str | None = Field(default=None, max_length=255)
    content_base64: str | None = None
    content_type: str = Field(default="application/json", max_length=128)
    payload: dict[str, Any] | None = None
    metadata_summary: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_content(self) -> "DataSourceScanItem":
        if self.content_base64 is None and self.payload is None:
            raise ValueError("either content_base64 or payload is required")
        return self


class DataSourceScanTaskCreate(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=128)
    owner_user_id: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    items: list[DataSourceScanItem] = Field(min_length=1)


class DataSourceScanTaskRead(BaseModel):
    batch: IngestBatchRead
    items: list[IngestFileAppendRead]


class AIGovernanceRunRead(ORMModel):
    id: str
    normalized_ref_id: str
    profile_id: str
    model_alias: str
    prompt_version: str
    input_hash: str
    input_summary: dict[str, Any]
    ai_output: dict[str, Any] | None
    quality_summary: dict[str, Any] | None
    validation_status: AIGovernanceRunValidationStatus
    adoption_status: AIGovernanceRunAdoptionStatus
    validation_error: str | None
    call_latency_ms: float | None
    request_id: str | None
    created_by: str | None
    trace_id: str | None
    created_at: datetime


class GovernanceResultRead(ORMModel):
    id: str
    normalized_ref_id: str
    ai_run_id: str | None
    classification: str | None
    level: str | None
    tags: list[str]
    org_scope: str | None
    index_admission: bool
    quality_summary: dict[str, Any] | None
    decision_trail: list[dict[str, Any]]
    rules_schema_version: str | None
    rules_content_hash: str | None
    status: str
    created_by: str | None
    trace_id: str | None
    created_at: datetime
    updated_at: datetime
