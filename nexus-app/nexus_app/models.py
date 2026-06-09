from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus_app.database import Base
from nexus_app.enums import (
    AIGovernanceRunAdoptionStatus,
    AIGovernanceRunValidationStatus,
    AuditEventType,
    AssetKind,
    AssetVersionStatus,
    ChunkingMode,
    ChunkingStrategy,
    ChunkType,
    DataSourceStatus,
    DataSourceType,
    EmbeddingStatus,
    GovernanceResultStatus,
    IndexManifestStatus,
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
    SourceKind,
    StageStatus,
    UserRole,
)


def new_uuid() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class OrgUnit(TimestampMixin, Base):
    __tablename__ = "org_unit"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("org_unit.id"), nullable=True
    )
    status: Mapped[OrgUnitStatus] = mapped_column(
        Enum(OrgUnitStatus, values_callable=lambda enum: [item.value for item in enum]),
        default=OrgUnitStatus.ACTIVE,
        nullable=False,
    )

    parent: Mapped["OrgUnit | None"] = relationship(remote_side=[id])


class UserAccount(TimestampMixin, Base):
    __tablename__ = "user_account"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
    )
    org_unit_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("org_unit.id"), nullable=True
    )
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[PrincipalStatus] = mapped_column(
        Enum(PrincipalStatus, values_callable=lambda enum: [item.value for item in enum]),
        default=PrincipalStatus.ACTIVE,
        nullable=False,
    )
    # bcrypt hash (~60 chars). NULL = SSO/external-only user, no password login.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Brute-force throttling — reset to 0 on every successful login. When the
    # counter reaches `MAX_FAILED_LOGIN_ATTEMPTS` (see `auth_service`), the
    # row gets stamped with `lockout_until` and further login attempts are
    # refused with 429 until that timestamp passes.
    failed_login_count: Mapped[int] = mapped_column(default=0, nullable=False)
    lockout_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    org_unit: Mapped[OrgUnit | None] = relationship()


class RefreshToken(TimestampMixin, Base):
    """Persisted refresh-token records backing the JWT auth flow.

    The JWT itself is never stored — only `jti` (the unique token id encoded in
    the JWT payload). On `/v1/auth/refresh`, we look up the row by jti, check it
    is not expired or revoked, then revoke it and mint a fresh one (rotation).
    `parent_jti` keeps a thin chain for forensics on token replay.
    """
    __tablename__ = "refresh_token"
    __table_args__ = (
        Index("ix_refresh_token_user_id", "user_id"),
        Index("ix_refresh_token_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    jti: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_account.id"), nullable=False
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parent_jti: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[UserAccount] = relationship()


class ApiCaller(TimestampMixin, Base):
    __tablename__ = "api_caller"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # Legacy plaintext caller_key — preserved for backward-compat with seed data
    # and existing tests, but new server-minted callers leave this NULL and store
    # only the sha256 hash. Lookups during request authentication use caller_key_hash.
    caller_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # sha256(caller_key) hex digest. Populated on every new caller; backfilled
    # for legacy rows by the same migration that adds this column.
    caller_key_hash: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    org_scope: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    permission_scope: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user_account.id"), nullable=True
    )

    owner_user: Mapped[UserAccount | None] = relationship()


class DataSource(TimestampMixin, Base):
    __tablename__ = "data_source"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_type: Mapped[DataSourceType] = mapped_column(
        Enum(DataSourceType, values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
    )
    status: Mapped[DataSourceStatus] = mapped_column(
        Enum(DataSourceStatus, values_callable=lambda enum: [item.value for item in enum]),
        default=DataSourceStatus.ENABLED,
        nullable=False,
    )
    owner_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user_account.id"), nullable=True
    )
    org_scope_hint: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False, comment="List of org_unit codes"
    )
    default_governance_hints: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
        comment="GovernanceHints schema: sensitivity_level, quality_threshold, etc.",
    )
    connection_config: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Source-type specific config: NasConnectionConfig, CrawlerConnectionConfig, etc.",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Soft-delete tombstone. NULL = live; populated = removed from list/get APIs.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner_user: Mapped[UserAccount | None] = relationship()


class IngestBatch(TimestampMixin, Base):
    __tablename__ = "ingest_batch"
    __table_args__ = (
        UniqueConstraint("data_source_id", "idempotency_key", name="uq_ingest_batch_source_idem"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    data_source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("data_source.id"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source_type: Mapped[DataSourceType] = mapped_column(
        Enum(DataSourceType, values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
    )
    status: Mapped[IngestBatchStatus] = mapped_column(
        Enum(IngestBatchStatus, values_callable=lambda enum: [item.value for item in enum]),
        default=IngestBatchStatus.SUBMITTED,
        nullable=False,
    )
    owner_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user_account.id"), nullable=True
    )
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    batch_status_detail: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
        comment="Per-raw-object status snapshot keyed by raw_object_id; updated by aggregator.",
    )

    data_source: Mapped[DataSource] = relationship()
    owner_user: Mapped[UserAccount | None] = relationship()


class RawObject(TimestampMixin, Base):
    __tablename__ = "raw_object"
    __table_args__ = (
        UniqueConstraint("data_source_id", "checksum", name="uq_raw_object_source_checksum"),
        UniqueConstraint(
            "batch_id", "file_idempotency_key", name="uq_raw_object_batch_file_idem"
        ),
        Index("ix_raw_object_batch_id", "batch_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    batch_id: Mapped[str] = mapped_column(String(36), ForeignKey("ingest_batch.id"), nullable=False)
    file_idempotency_key: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="Caller-supplied idempotency key for multi-raw batch file append; NULL for legacy single-file ingest.",
    )
    data_source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("data_source.id"), nullable=False
    )
    source_type: Mapped[DataSourceType] = mapped_column(
        Enum(DataSourceType, values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
    )
    source_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    object_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[RawObjectStatus] = mapped_column(
        Enum(RawObjectStatus, values_callable=lambda enum: [item.value for item in enum]),
        default=RawObjectStatus.RAW_PERSISTED,
        nullable=False,
    )
    metadata_summary: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
        comment="Source-type specific: RawObjectMetadataFile, RawObjectMetadataCrawler, etc.",
    )

    batch: Mapped[IngestBatch] = relationship()
    data_source: Mapped[DataSource] = relationship()


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_target", "target_type", "target_id"),
        Index("ix_audit_log_trace_id", "trace_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    event_type: Mapped[AuditEventType] = mapped_column(
        Enum(AuditEventType, values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
    )
    actor_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Job(TimestampMixin, Base):
    __tablename__ = "job"
    __table_args__ = (
        Index("ix_job_ingest_batch_id", "ingest_batch_id"),
        Index("ix_job_raw_object_id", "raw_object_id"),
        Index("idx_job_polling", "status", "next_run_at", "priority", "created_at"),
        # Partial index `idx_job_running_lock_expiry ON job(lock_expires_at)
        # WHERE status='running'` lives in Alembic 0021 (PostgreSQL-only).
        # Not declared here because SQLAlchemy's `postgresql_where` would
        # silently turn into a full index on SQLite, which is both wasteful
        # and inconsistent with the production schema.
        Index("idx_job_idempotency", "job_type", "idempotency_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    job_type: Mapped[JobType] = mapped_column(
        Enum(JobType, values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, values_callable=lambda enum: [item.value for item in enum]),
        default=JobStatus.QUEUED,
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(
        default=100,
        nullable=False,
        comment="Lower value = higher priority (e.g., 10 > 100 > 200)",
    )
    ingest_batch_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ingest_batch.id"), nullable=True
    )
    raw_object_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("raw_object.id"), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(default=3, nullable=False)
    retry_count: Mapped[int] = mapped_column(default=0, nullable=False)
    current_stage: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    # Stamped at queue time so the worker can refuse jobs whose payload schema
    # it does not recognize (e.g. older queued jobs after a payload evolution).
    # Current value: see `nexus_app.pipeline.payload_schema.JOB_PAYLOAD_SCHEMA_VERSION`.
    payload_schema_version: Mapped[str] = mapped_column(
        String(16), default="v1", nullable=False
    )
    metadata_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    # Operator cancel signal. Set by POST /v1/jobs/{id}/cancel when the job is
    # currently RUNNING; the worker honors it at the next stage boundary.
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    ingest_batch: Mapped[IngestBatch | None] = relationship()
    raw_object: Mapped[RawObject | None] = relationship()


class JobStage(TimestampMixin, Base):
    __tablename__ = "job_stage"
    __table_args__ = (Index("ix_job_stage_job_id", "job_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("job.id"), nullable=False)
    stage_name: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[StageStatus] = mapped_column(
        Enum(StageStatus, values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    job: Mapped[Job] = relationship()


class Asset(TimestampMixin, Base):
    # Table renamed `document_asset` → `asset` in Alembic 0020 to align with
    # ARCHITECT.md. Python class name preserved to avoid a separate cascade
    # through console TypeScript types in this PR.
    __tablename__ = "asset"
    __table_args__ = (
        UniqueConstraint("data_source_id", "source_object_key", name="uq_asset_source_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    data_source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("data_source.id"), nullable=False
    )
    source_object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    asset_kind: Mapped[AssetKind] = mapped_column(
        Enum(AssetKind, values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
    )
    status: Mapped[AssetVersionStatus] = mapped_column(
        Enum(AssetVersionStatus, values_callable=lambda enum: [item.value for item in enum]),
        default=AssetVersionStatus.PROCESSING,
        nullable=False,
    )
    org_scope: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    metadata_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    data_source: Mapped[DataSource] = relationship()


class AssetVersion(TimestampMixin, Base):
    # Table renamed `document_version` → `asset_version` in Alembic 0020.
    __tablename__ = "asset_version"
    # Partial unique index `uq_asset_version_one_available_per_asset` is
    # PostgreSQL-only and lives in Alembic 0014. Not declared here because
    # SQLAlchemy's `postgresql_where` is silently ignored by SQLite and would
    # create a full UNIQUE(asset_id) — fatally broken for non-PG environments.
    __table_args__ = (
        UniqueConstraint("asset_id", "version_no", name="uq_asset_version_asset_no"),
        Index("ix_asset_version_asset_status", "asset_id", "version_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("asset.id"), nullable=False
    )
    raw_object_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("raw_object.id"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(nullable=False)
    version_status: Mapped[AssetVersionStatus] = mapped_column(
        Enum(AssetVersionStatus, values_callable=lambda enum: [item.value for item in enum]),
        default=AssetVersionStatus.PROCESSING,
        nullable=False,
    )
    source_checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    asset: Mapped[Asset] = relationship()
    raw_object: Mapped[RawObject] = relationship()


class ParseArtifact(TimestampMixin, Base):
    __tablename__ = "parse_artifact"
    __table_args__ = (Index("ix_parse_artifact_raw_object_id", "raw_object_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    raw_object_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("raw_object.id"), nullable=False
    )
    asset_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("asset_version.id"), nullable=True
    )
    artifact_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    parse_mode: Mapped[str] = mapped_column(String(80), nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[ParseArtifactStatus] = mapped_column(
        Enum(ParseArtifactStatus, values_callable=lambda enum: [item.value for item in enum]),
        default=ParseArtifactStatus.GENERATED,
        nullable=False,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    raw_object: Mapped[RawObject] = relationship()
    asset_version: Mapped[AssetVersion | None] = relationship()


class NormalizedAssetRef(TimestampMixin, Base):
    __tablename__ = "normalized_asset_ref"
    __table_args__ = (
        Index("ix_normalized_asset_ref_version_id", "version_id"),
        Index("ix_normalized_asset_ref_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("asset_version.id"), nullable=False
    )
    normalized_type: Mapped[NormalizedType] = mapped_column(
        Enum(NormalizedType, values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
    )
    object_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[NormalizedAssetRefStatus] = mapped_column(
        Enum(NormalizedAssetRefStatus, values_callable=lambda enum: [item.value for item in enum]),
        default=NormalizedAssetRefStatus.GENERATED,
        nullable=False,
    )
    block_count: Mapped[int] = mapped_column(default=0, nullable=False)
    record_count: Mapped[int] = mapped_column(default=0, nullable=False)
    # Governance fields — populated by normalize-service from source contract and content analysis
    source_type: Mapped[str | None] = mapped_column(String(40), nullable=True,
        comment="DataSourceType value copied from raw_object for fast filtering")
    content_type: Mapped[str | None] = mapped_column(String(40), nullable=True,
        comment="Semantic content type: document/slide_deck/table_sheet/web_record/media_meta")
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True,
        comment="Primary language code, e.g. zh-CN")
    governance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False,
        comment="Classification, sensitivity level, org_scope, version_status snapshot")
    quality: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False,
        comment="Quality scores, anomaly items, manual review status")
    lineage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False,
        comment="raw_object_id, parse_artifact_id, processing chain trace")
    metadata_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False,
        comment="Source, business, temporal metadata for search enrichment")

    version: Mapped[AssetVersion] = relationship()


class AIPromptProfile(TimestampMixin, Base):
    """AI Prompt configuration with version management."""
    __tablename__ = "ai_prompt_profile"
    __table_args__ = (
        Index("ix_ai_prompt_profile_name_status", "profile_name", "status"),
        UniqueConstraint("profile_name", "profile_version", name="uq_ai_prompt_profile_name_ver"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    profile_name: Mapped[str] = mapped_column(String(128), nullable=False)
    profile_version: Mapped[int] = mapped_column(nullable=False, default=1)
    task_type: Mapped[str] = mapped_column(String(80), nullable=False)
    scenario: Mapped[str] = mapped_column(String(80), nullable=False, default="default")
    status: Mapped[PromptProfileStatus] = mapped_column(
        Enum(PromptProfileStatus, values_callable=lambda enum: [item.value for item in enum]),
        default=PromptProfileStatus.ACTIVE,
        nullable=False,
    )
    litellm_model_alias: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    output_schema_version: Mapped[str] = mapped_column(String(40), nullable=False, default="1.0")
    scoring_weight_version: Mapped[str] = mapped_column(String(40), nullable=False, default="1.0")
    temperature: Mapped[float] = mapped_column(nullable=False, default=0.2)
    max_input_tokens: Mapped[int] = mapped_column(nullable=False, default=4096)
    redaction_policy: Mapped[str] = mapped_column(String(64), nullable=False,
                                                   default="masked_content")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AIGovernanceRun(TimestampMixin, Base):
    """AI governance execution record — one record per LiteLLM call."""
    __tablename__ = "ai_governance_run"
    __table_args__ = (
        Index("ix_ai_governance_run_ref_id", "normalized_ref_id"),
        Index("ix_ai_governance_run_profile_id", "profile_id"),
        Index("ix_ai_governance_run_validation_status", "validation_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    normalized_ref_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("normalized_asset_ref.id"), nullable=False
    )
    profile_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ai_prompt_profile.id"), nullable=False
    )
    model_alias: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    quality_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    validation_status: Mapped[AIGovernanceRunValidationStatus] = mapped_column(
        Enum(AIGovernanceRunValidationStatus,
             values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
        default=AIGovernanceRunValidationStatus.FAILED,
    )
    adoption_status: Mapped[AIGovernanceRunAdoptionStatus] = mapped_column(
        Enum(AIGovernanceRunAdoptionStatus,
             values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
        default=AIGovernanceRunAdoptionStatus.REVIEW_REQUIRED,
    )
    validation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    call_latency_ms: Mapped[float | None] = mapped_column(nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    normalized_ref: Mapped[NormalizedAssetRef] = relationship()
    profile: Mapped[AIPromptProfile] = relationship()


class GovernanceResult(TimestampMixin, Base):
    """Official governance result for a normalized_asset_ref.

    Records the governance_rules.json snapshot (schema_version + content_hash)
    used at decision time, so historical results stay interpretable even after
    rules are edited.
    """
    __tablename__ = "governance_result"
    __table_args__ = (
        Index("ix_governance_result_normalized_ref_id", "normalized_ref_id"),
        Index("ix_governance_result_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    normalized_ref_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("normalized_asset_ref.id"), nullable=False
    )
    ai_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ai_governance_run.id"), nullable=True
    )
    classification: Mapped[str | None] = mapped_column(String(40), nullable=True)
    level: Mapped[str | None] = mapped_column(String(8), nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    org_scope: Mapped[str | None] = mapped_column(String(128), nullable=True)
    index_admission: Mapped[bool] = mapped_column(nullable=False, default=False)
    quality_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True,
        comment="Embedded QualitySummary payload from AI governance run")
    decision_trail: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list,
        nullable=False, comment="List of DecisionTrail entries")
    rules_schema_version: Mapped[str | None] = mapped_column(String(32), nullable=True,
        comment="schema_version of governance_rules.json at decision time")
    rules_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True,
        comment="sha256 of governance_rules.json content at decision time")
    status: Mapped[GovernanceResultStatus] = mapped_column(
        Enum(GovernanceResultStatus, values_callable=lambda e: [i.value for i in e]),
        nullable=False, default=GovernanceResultStatus.REVIEW_REQUIRED,
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    normalized_ref: Mapped[NormalizedAssetRef] = relationship()
    ai_run: Mapped[AIGovernanceRun | None] = relationship()


class IndexManifest(TimestampMixin, Base):
    """RAGFlow index manifest for a (normalized_asset_ref, knowledge_type_code) pair.

    One ref can produce multiple manifests — one per emitted knowledge type —
    because each knowledge type targets its own RAGFlow dataset (KB) with a
    distinct chunk_method. The (normalized_ref_id, knowledge_type_code) pair is
    unique among INDEXED manifests so retries don't double-write.
    """
    __tablename__ = "index_manifest"
    __table_args__ = (
        Index("ix_index_manifest_normalized_ref_id", "normalized_ref_id"),
        Index("ix_index_manifest_kt_code", "knowledge_type_code"),
        UniqueConstraint(
            "normalized_ref_id", "knowledge_type_code",
            name="uq_index_manifest_ref_kt",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    normalized_ref_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("normalized_asset_ref.id"), nullable=False
    )
    knowledge_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    index_status: Mapped[IndexManifestStatus] = mapped_column(
        Enum(IndexManifestStatus, values_callable=lambda e: [i.value for i in e]),
        nullable=False, default=IndexManifestStatus.PENDING,
    )
    ragflow_kb_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ragflow_doc_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    chunk_count: Mapped[int] = mapped_column(nullable=False, default=0)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    normalized_ref: Mapped[NormalizedAssetRef] = relationship()


class KnowledgeChunk(TimestampMixin, Base):
    """Knowledge unit produced by Knowledge Pipeline from a normalized_asset_ref."""
    __tablename__ = "knowledge_chunk"
    __table_args__ = (
        Index("ix_knowledge_chunk_ref_type", "normalized_ref_id", "knowledge_type_code"),
        Index("ix_knowledge_chunk_type_created", "knowledge_type_code", "created_at"),
        Index("ix_knowledge_chunk_ragflow_doc", "ragflow_doc_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    normalized_ref_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("normalized_asset_ref.id"), nullable=False
    )
    knowledge_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_type: Mapped[ChunkType] = mapped_column(
        Enum(ChunkType, values_callable=lambda e: [i.value for i in e]),
        nullable=False,
    )
    chunking_strategy: Mapped[ChunkingStrategy] = mapped_column(
        Enum(ChunkingStrategy, values_callable=lambda e: [i.value for i in e]),
        nullable=False,
    )
    source_kind: Mapped[SourceKind] = mapped_column(
        Enum(SourceKind, values_callable=lambda e: [i.value for i in e]),
        nullable=False, default=SourceKind.EXTRACTED_FROM_NORMALIZED,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict, nullable=False
    )
    co_emission_origin: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ragflow_chunk_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ragflow_doc_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ragflow_chunk_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_status: Mapped[EmbeddingStatus] = mapped_column(
        Enum(EmbeddingStatus, values_callable=lambda e: [i.value for i in e]),
        nullable=False, default=EmbeddingStatus.PENDING,
    )

    normalized_ref: Mapped[NormalizedAssetRef] = relationship()