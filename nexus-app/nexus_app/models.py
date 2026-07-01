from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

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
    GovernancePromptTemplateStatus,
    GovernanceRulesVersionStatus,
    GovernanceTaskType,
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
    rotated_to_jti: Mapped[str | None] = mapped_column(String(64), nullable=True)

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
    # Document-level metadata extracted from blocks during normalize (RFC §17).
    # Shape (all keys optional):
    #   title, subtitle, authors[], publish_date (ISO yyyy or yyyy-mm),
    #   publisher, doc_number, version, language, keywords[], abstract,
    #   outline[{level, title, page, ...}], source_block_ids[]
    # Belongs HERE (not in per-chunk chunk_metadata) so the same document
    # title / author / abstract is not duplicated into every RAG chunk
    # (chunks-table-growth concern, see docs/blocks_to_rag_chunks_optimization.md §三.3).
    document_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True,
        comment="Document-level metadata extracted from blocks (title, authors, "
                "publish_date, keywords, abstract, outline, source_block_ids). "
                "Used as every chunk's parent context and asset-detail rendering; "
                "NEVER duplicated into per-chunk metadata.")

    version: Mapped[AssetVersion] = relationship()


class AIPromptProfile(TimestampMixin, Base):
    """AI Prompt configuration with version management.

    B5.1 (Pipeline B knowledge-unit extraction + body_markdown rendering)
    extends this table with three nullable fields per
    `docs/pipeline_b_contract_freeze.md §九`:
      - `domain`            — business-domain label ("occupation", …)
      - `rules_object_type` — initial whitelist: `ai_analysis_rules` only
      - `rules_object_code` — business key like `<rule_set_code>:<version>`
    All three default NULL so legacy governance-phase prompts keep working
    without backfill. The CHECK constraint is declared in the migration
    rather than at the ORM layer so dialect differences (PG vs SQLite test)
    don't leak into the model.
    """
    __tablename__ = "ai_prompt_profile"
    __table_args__ = (
        Index("ix_ai_prompt_profile_name_status", "profile_name", "status"),
        Index("ix_ai_prompt_profile_scenario", "scenario"),
        UniqueConstraint("profile_name", "profile_version", name="uq_ai_prompt_profile_name_ver"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    profile_name: Mapped[str] = mapped_column(String(128), nullable=False)
    profile_version: Mapped[int] = mapped_column(nullable=False, default=1)
    task_type: Mapped[str] = mapped_column(String(80), nullable=False)
    scenario: Mapped[str] = mapped_column(String(80), nullable=False, default="default")
    domain: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rules_object_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rules_object_code: Mapped[str | None] = mapped_column(String(256), nullable=True)
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


class AIAnalysisRules(TimestampMixin, Base):
    """Pipeline B knowledge-unit extraction + body_markdown render rule sets.

    Schema-frozen by `docs/pipeline_b_contract_freeze.md §5.4` (+ §八). Each
    row carries one immutable `(rule_set_code, version)` pair; rule mutations
    must add a new `version` row rather than mutating existing ones (per
    freeze §八 "重跑 seed 不允许覆盖已激活规则的语义").

    Source of truth is **this PG table**, not `config/ai_analysis_rules.json`.
    The JSON file is a seed only — the loader inserts missing
    `(rule_set_code, version)` rows and never updates existing ones
    (see `nexus_app/knowledge_extraction/rules_loader.py`).

    Why we did NOT reuse `governance_rules_version`:
    - Different concept owner (knowledge-unit extraction vs data-asset
      governance) — see CLAUDE.md "AI Governance Contract" + decision §12.5
    - Different writer / consumer modules — keep them separated so a
      governance-rules schema change doesn't drag the extraction rules
      with it (and vice versa)
    """
    __tablename__ = "ai_analysis_rules"
    __table_args__ = (
        UniqueConstraint("rule_set_code", "version", name="uq_aar_code_version"),
        Index("ix_aar_scenario", "scenario"),
        Index("ix_aar_active", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    rule_set_code: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    scenario: Mapped[str] = mapped_column(String(80), nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    # output_format: 'json' (default) or 'markdown'. CHECK enforced in migration.
    output_format: Mapped[str] = mapped_column(String(16), default="json", nullable=False)
    output_contract: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # JSON-output schema. NULL when output_format='markdown' (CHECK enforced
    # in the migration: exactly one of output_item_schema / markdown_skeleton
    # is populated for any given row).
    output_item_schema: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Markdown-output skeleton (required headings, field blocks, length cap,
    # overflow template). NULL when output_format='json'.
    markdown_skeleton: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    field_whitelist: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    guardrails: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    auto_admit_threshold: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    owner_module: Mapped[str] = mapped_column(
        String(64), nullable=False, default="knowledge_unit_extraction"
    )
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # 'reject' (default) drops the result on failure; 'deterministic_template'
    # falls back to a code-side renderer (only meaningful with output_format=
    # 'markdown'). CHECK enforced in migration.
    fallback_strategy: Mapped[str] = mapped_column(
        String(32), default="reject", nullable=False
    )
    initialized_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    initialized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


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
    profile_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ai_prompt_profile.id"), nullable=True
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
    prompt_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True,
        comment="Snapshot of prompt template ids used for multi-stage governance")

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
    rules_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("governance_rules_version.id"), nullable=True,
        comment="FK to governance_rules_version used at decision time")
    status: Mapped[GovernanceResultStatus] = mapped_column(
        Enum(GovernanceResultStatus, values_callable=lambda e: [i.value for i in e]),
        nullable=False, default=GovernanceResultStatus.REVIEW_REQUIRED,
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    normalized_ref: Mapped[NormalizedAssetRef] = relationship()
    ai_run: Mapped[AIGovernanceRun | None] = relationship()
    rules_version: Mapped["GovernanceRulesVersion | None"] = relationship()


class GovernanceRulesVersion(TimestampMixin, Base):
    """Versioned governance rules definition — only one active at a time."""
    __tablename__ = "governance_rules_version"
    __table_args__ = (
        Index("ix_grv_status", "status"),
        Index("uq_grv_active", "status", unique=True,
              postgresql_where=text("status = 'active'")),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[GovernanceRulesVersionStatus] = mapped_column(
        Enum(GovernanceRulesVersionStatus, values_callable=lambda e: [i.value for i in e]),
        default=GovernanceRulesVersionStatus.ACTIVE, nullable=False)
    rules_content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    change_summary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class GovernancePromptTemplate(TimestampMixin, Base):
    """Governance prompt template — one active per task_type at a time."""
    __tablename__ = "governance_prompt_template"
    __table_args__ = (
        Index("ix_gpt_task_type", "task_type"),
        Index("ix_gpt_status", "status"),
        Index("uq_gpt_task_type_active", "task_type", unique=True,
              postgresql_where=text("status = 'active'")),
        UniqueConstraint("task_type", "template_version",
                         name="uq_gpt_task_type_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    task_type: Mapped[str] = mapped_column(String(80), nullable=False)
    template_name: Mapped[str] = mapped_column(String(128), nullable=False)
    template_version: Mapped[int] = mapped_column(nullable=False, default=1)
    status: Mapped[GovernancePromptTemplateStatus] = mapped_column(
        Enum(GovernancePromptTemplateStatus, values_callable=lambda e: [i.value for i in e]),
        default=GovernancePromptTemplateStatus.ACTIVE, nullable=False)
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    output_schema_version: Mapped[str] = mapped_column(String(40), nullable=False, default="1.0")
    litellm_model_alias: Mapped[str] = mapped_column(String(128), nullable=False)
    temperature: Mapped[float] = mapped_column(nullable=False, default=0.2)
    max_input_tokens: Mapped[int] = mapped_column(nullable=False, default=4096)
    redaction_policy: Mapped[str] = mapped_column(String(64), nullable=False,
                                                   default="masked_content")
    change_summary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


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
    embedding_status: Mapped[EmbeddingStatus] = mapped_column(
        Enum(EmbeddingStatus, values_callable=lambda e: [i.value for i in e]),
        nullable=False, default=EmbeddingStatus.PENDING,
    )
    # Origin block_ids in normalized_document.blocks[]. Null for record-type chunks
    # or legacy rows where source provenance was not preserved.
    source_block_ids: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True
    )
    # Coordinate locator contract — see ARCHITECT.md "Chunk Locator Contract".
    # Shape: {page_start, page_end, bbox_union, blocks: [{block_id, page, bbox}]}
    locator: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    normalized_ref: Mapped[NormalizedAssetRef] = relationship()




# ---------------------------------------------------------------------------
# Pipeline B B4 — job_demand domain tables
# ---------------------------------------------------------------------------
# Schemas frozen by `docs/pipeline_b_contract_freeze.md §5.1 / §5.2 / §5.3` +
# `docs/pipeline_b_b4_b6_contract_freeze.md §一 / §二.1 / §三 / §六`.
# Written by `nexus_app/domain_normalize/job_demand_writer.py`. Invariants:
#   - one `job_demand_dataset` per `normalized_ref_id` (B4 dataset-level
#     idempotency; re-runs delete+reinsert via the cascade FKs below)
#   - records cascade-delete from dataset; requirement-items cascade from both
#   - dedup uses `record_fingerprint` (sha256 of NFKC-normalised company /
#     title / city / source_record_key) — B5 reads the same field
#   - JSON columns mirror `governance` / `quality` / `lineage` style on
#     NormalizedAssetRef (works on Postgres JSONB AND the SQLite test harness)


class JobDemandDataset(TimestampMixin, Base):
    """One job-demand dataset per normalized_asset_ref (B4 writer entry).

    `normalized_ref_id` is unique — re-running the writer for the same ref
    deletes this row (with cascade) and re-inserts, per §三.3 of the b4/b6
    freeze. `quality_summary` aggregates the per-record `quality_flags` counts
    plus dataset-level flags like `unknown_source_channel`; see
    `JobDemandRecord.quality_flags` for the closed flag vocabulary.
    """
    __tablename__ = "job_demand_dataset"
    __table_args__ = (
        # Frozen index names (§5.1 of pipeline_b_contract_freeze). Unique on
        # normalized_ref_id enforces "one dataset per ref" without needing a
        # separate UniqueConstraint object.
        Index("ix_jdd_normalized_ref_id", "normalized_ref_id", unique=True),
        Index("ix_jdd_asset_version_id", "asset_version_id"),
        Index("ix_jdd_major", "major_name"),
        Index("ix_jdd_industry", "industry_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    normalized_ref_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("normalized_asset_ref.id"), nullable=False
    )
    asset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("asset_version.id"), nullable=False,
        comment="Redundant copy of normalized_ref.version_id for fast filtering"
    )
    major_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    industry_name: Mapped[str | None] = mapped_column(Text, nullable=True,
        comment="Default industry; can be overridden at record level")
    source_channel: Mapped[str] = mapped_column(Text, nullable=False,
        comment="excel_upload / crawler / database / manual_import; "
                "values outside the whitelist write unknown_source_channel "
                "flag to quality_summary")
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    schema_version: Mapped[str] = mapped_column(Text, nullable=False,
        comment="Mirrors normalized_record.payload.schema_version "
                "(e.g. 'job_demand.v1')")
    quality_summary: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
        comment="Aggregated counts of per-record quality_flags + dataset-level "
                "flags (unknown_source_channel etc.)"
    )

    normalized_ref: Mapped[NormalizedAssetRef] = relationship()
    records: Mapped[list["JobDemandRecord"]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class JobDemandRecord(TimestampMixin, Base):
    """A single job posting derived from a row in the source dataset.

    `record_fingerprint` is `sha256(NFKC(company)|NFKC(title)|NFKC(city)|
    NFKC(source_record_key))` — computed in `domain_normalize/fingerprint.py`
    so B5 / B7 / Pipeline B testing all share one definition. The unique
    constraint is scoped to `(dataset_id, fingerprint)` per §三.1 of the
    b4/b6 freeze: different datasets are allowed to carry the same posting
    (e.g. a crawler dataset vs an excel-upload dataset).
    """
    __tablename__ = "job_demand_record"
    __table_args__ = (
        Index("ix_jdr_dataset_id", "dataset_id"),
        Index("ix_jdr_normalized_ref_id", "normalized_ref_id"),
        Index("ix_jdr_city", "city"),
        Index("ix_jdr_industry", "industry_name"),
        Index("ix_jdr_enterprise_size", "enterprise_size"),
        Index("ix_jdr_employment_type", "employment_type"),
        # §三.1 / §5.2 — dataset-scoped dedup of (company, title, city,
        # source_record_key) tuples after NFKC normalization.
        UniqueConstraint(
            "dataset_id", "record_fingerprint", name="uq_jdr_dataset_fingerprint"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    dataset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("job_demand_dataset.id", ondelete="CASCADE"),
        nullable=False,
    )
    normalized_ref_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("normalized_asset_ref.id"), nullable=False,
        comment="Governance traceability — same ref as the dataset row"
    )
    source_record_key: Mapped[str] = mapped_column(Text, nullable=False,
        comment="Crawler record id OR sheet+row hash; never NULL")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_platform: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="ISO8601 parsed; parse failures keep NULL + "
                "quality_flags.published_at_unparsed"
    )
    job_title: Mapped[str] = mapped_column(Text, nullable=False,
        comment="Required — rows missing this are dropped as invalid")
    employment_type: Mapped[str | None] = mapped_column(Text, nullable=True,
        comment="Raw text — full_time / part_time / intern / ...; no enum "
                "validation at this layer (decision 8)")
    job_function_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    city: Mapped[str | None] = mapped_column(Text, nullable=True,
        comment="Original text; combined forms like '城市+区' preserved verbatim")
    region: Mapped[str | None] = mapped_column(Text, nullable=True,
        comment="Parsed upstream; NULL + quality_flags.location_unparsed on "
                "parse failure")
    salary_min: Mapped[float | None] = mapped_column(nullable=True)
    salary_max: Mapped[float | None] = mapped_column(nullable=True)
    salary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    experience_requirement: Mapped[str | None] = mapped_column(Text, nullable=True)
    education_requirement: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    enterprise_size: Mapped[str | None] = mapped_column(Text, nullable=True,
        comment="Original text; P0 forbids any normalisation/bucketing "
                "(decision 7)")
    industry_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_skill_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsibility_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirement_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    record_fingerprint: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="sha256 hex of NFKC-normalised "
                "(company_name|job_title|city|source_record_key); "
                "see domain_normalize.fingerprint"
    )
    quality_flags: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
        comment="Closed vocabulary (§四 of b4/b6 freeze): location_unparsed, "
                "published_at_unparsed, placeholder_row_dropped, "
                "duplicate_fingerprint, missing_required_field, "
                "unknown_source_channel — never extend without a fresh freeze"
    )
    trace: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
        comment="{sheet, row, column?, source_record_key}"
    )

    dataset: Mapped[JobDemandDataset] = relationship(back_populates="records")
    normalized_ref: Mapped[NormalizedAssetRef] = relationship()


class JobDemandRequirementItem(TimestampMixin, Base):
    """B5-owned table — B4 only creates the schema (no writes from this slice).

    `rules_version_id` references `ai_analysis_rules.id`, which is the B5
    table. B4 deliberately models this as a plain `String(36)` *without* a
    SQLAlchemy FK because `ai_analysis_rules` is built in a separate B5
    migration; once both ship, a follow-up B5 migration can attach the FK
    constraint. The same caveat applies to `prompt_template_id`
    (`ai_prompt_profile` exists today but the link is B5-owned semantically).
    """
    __tablename__ = "job_demand_requirement_item"
    __table_args__ = (
        Index("ix_jdri_record_id", "record_id"),
        Index("ix_jdri_dataset_id", "dataset_id"),
        Index("ix_jdri_item_type", "item_type"),
        Index("ix_jdri_rules_version_id", "rules_version_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("job_demand_record.id", ondelete="CASCADE"),
        nullable=False,
    )
    dataset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("job_demand_dataset.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_type: Mapped[str] = mapped_column(Text, nullable=False,
        comment="App-layer whitelist: professional_skill / tool / certificate / "
                "professional_literacy / work_task_candidate")
    item_name: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    taxonomy_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(nullable=False,
        comment="Must be in [0, 1]; enforced by B5 writer, not DB")
    extractor_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_field: Mapped[str | None] = mapped_column(Text, nullable=True,
        comment="job_skill_text / job_description / requirement_text — which "
                "JobDemandRecord column the AI extraction sourced from")
    # NOTE: B5 ships `ai_analysis_rules`; until then `rules_version_id` is a
    # plain String(36) column with no FK constraint so this table can be
    # created independently of B5.
    prompt_template_id: Mapped[str | None] = mapped_column(String(36), nullable=True,
        comment="FK to ai_prompt_profile — semantic owner is B5, no DB FK "
                "constraint here")
    rules_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True,
        comment="FK to ai_analysis_rules (created by B5; DB constraint added "
                "by a later B5 migration)")
    ai_model_alias: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Pipeline B PD — major_distribution domain tables
# ---------------------------------------------------------------------------


class MajorDistributionDataset(TimestampMixin, Base):
    """One major-distribution dataset per normalized_asset_ref."""

    __tablename__ = "major_distribution_dataset"
    __table_args__ = (
        Index("ix_mdd_normalized_ref_id", "normalized_ref_id", unique=True),
        Index("ix_mdd_asset_version_id", "asset_version_id"),
        Index("ix_mdd_major_code", "major_code"),
        Index("ix_mdd_year_range", "year_min", "year_max"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    normalized_ref_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("normalized_asset_ref.id"), nullable=False
    )
    asset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("asset_version.id"), nullable=False
    )
    dataset_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_channel: Mapped[str] = mapped_column(Text, nullable=False)
    major_scope: Mapped[str] = mapped_column(Text, nullable=False)
    major_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    major_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    education_level: Mapped[str | None] = mapped_column(Text, nullable=True)
    year_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    province_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    placeholder_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ignored_summary_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    quality_summary: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )

    normalized_ref: Mapped[NormalizedAssetRef] = relationship()
    records: Mapped[list["MajorDistributionRecord"]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class MajorDistributionRecord(TimestampMixin, Base):
    """A single non-summary major distribution detail row."""

    __tablename__ = "major_distribution_record"
    __table_args__ = (
        Index("ix_mdr_dataset_id", "dataset_id"),
        Index("ix_mdr_normalized_ref_id", "normalized_ref_id"),
        Index("ix_mdr_major_code", "major_code"),
        Index("ix_mdr_major_name", "major_name"),
        Index("ix_mdr_year", "year"),
        Index("ix_mdr_province", "province_name"),
        Index("ix_mdr_region_scope", "region_scope"),
        Index("ix_mdr_education_level", "education_level"),
        UniqueConstraint(
            "dataset_id", "source_record_key",
            name="uq_mdr_dataset_source_record_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    dataset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("major_distribution_dataset.id", ondelete="CASCADE"),
        nullable=False,
    )
    normalized_ref_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("normalized_asset_ref.id"), nullable=False
    )
    source_record_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_row_no: Mapped[str | None] = mapped_column(Text, nullable=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    year_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    province_name: Mapped[str] = mapped_column(Text, nullable=False)
    region_scope: Mapped[str] = mapped_column(Text, nullable=False)
    major_name: Mapped[str] = mapped_column(Text, nullable=False)
    major_code: Mapped[str] = mapped_column(Text, nullable=False)
    education_level: Mapped[str | None] = mapped_column(Text, nullable=True)
    distribution_count: Mapped[int] = mapped_column(Integer, nullable=False)
    quality_flags: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    trace: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )

    dataset: Mapped[MajorDistributionDataset] = relationship(back_populates="records")
    normalized_ref: Mapped[NormalizedAssetRef] = relationship()


# ---------------------------------------------------------------------------
# Pipeline A MP — major_profile domain tables
# ---------------------------------------------------------------------------


class MajorProfile(TimestampMixin, Base):
    """Professional introduction/profile extracted from a normalized document."""

    __tablename__ = "major_profile"
    __table_args__ = (
        Index("ix_mp_normalized_ref_id", "normalized_ref_id"),
        Index("ix_mp_asset_version_id", "asset_version_id"),
        Index("ix_mp_major_code", "major_code"),
        Index("ix_mp_major_name", "major_name"),
        UniqueConstraint(
            "normalized_ref_id", "major_code", "major_name",
            name="uq_mp_ref_code_name",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    normalized_ref_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("normalized_asset_ref.id"), nullable=False
    )
    asset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("asset_version.id"), nullable=False
    )
    domain_profile: Mapped[str] = mapped_column(Text, nullable=False)
    major_code: Mapped[str] = mapped_column(Text, nullable=False)
    major_name: Mapped[str] = mapped_column(Text, nullable=False)
    education_level: Mapped[str | None] = mapped_column(Text, nullable=True)
    basic_study_duration: Mapped[str | None] = mapped_column(Text, nullable=True)
    training_goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    extractor_version: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    quality_flags: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="generated")

    normalized_ref: Mapped[NormalizedAssetRef] = relationship()
    occupations: Mapped[list["MajorProfileOccupation"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", passive_deletes=True
    )
    abilities: Mapped[list["MajorProfileAbility"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", passive_deletes=True
    )
    courses: Mapped[list["MajorProfileCourse"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", passive_deletes=True
    )
    certificates: Mapped[list["MajorProfileCertificate"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", passive_deletes=True
    )
    continuations: Mapped[list["MajorProfileContinuation"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", passive_deletes=True
    )


class MajorProfileItemMixin:
    @declared_attr
    def id(cls) -> Mapped[str]:
        return mapped_column(String(36), primary_key=True, default=new_uuid)

    @declared_attr
    def profile_id(cls) -> Mapped[str]:
        return mapped_column(
            String(36), ForeignKey("major_profile.id", ondelete="CASCADE"), nullable=False
        )

    @declared_attr
    def normalized_ref_id(cls) -> Mapped[str]:
        return mapped_column(
            String(36), ForeignKey("normalized_asset_ref.id"), nullable=False
        )

    @declared_attr
    def item_index(cls) -> Mapped[int]:
        return mapped_column(Integer, nullable=False)

    @declared_attr
    def text(cls) -> Mapped[str]:
        return mapped_column(Text, nullable=False)

    @declared_attr
    def source_text(cls) -> Mapped[str | None]:
        return mapped_column(Text, nullable=True)

    @declared_attr
    def evidence_block_ids(cls) -> Mapped[list[str]]:
        return mapped_column(JSON, default=list, nullable=False)

    @declared_attr
    def locator(cls) -> Mapped[dict[str, Any]]:
        return mapped_column(JSON, default=dict, nullable=False)

    @declared_attr
    def confidence(cls) -> Mapped[float | None]:
        return mapped_column(nullable=True)


class MajorProfileOccupation(TimestampMixin, MajorProfileItemMixin, Base):
    __tablename__ = "major_profile_occupation"
    __table_args__ = (
        Index("ix_mpo_profile_id", "profile_id"),
        Index("ix_mpo_normalized_ref_id", "normalized_ref_id"),
        Index("ix_mpo_normalized_name", "normalized_name"),
    )

    normalized_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    occupation_type: Mapped[str] = mapped_column(Text, nullable=False, default="unknown")

    profile: Mapped[MajorProfile] = relationship(back_populates="occupations")
    normalized_ref: Mapped[NormalizedAssetRef] = relationship()


class MajorProfileAbility(TimestampMixin, MajorProfileItemMixin, Base):
    __tablename__ = "major_profile_ability"
    __table_args__ = (
        Index("ix_mpa_profile_id", "profile_id"),
        Index("ix_mpa_normalized_ref_id", "normalized_ref_id"),
    )

    profile: Mapped[MajorProfile] = relationship(back_populates="abilities")
    normalized_ref: Mapped[NormalizedAssetRef] = relationship()


class MajorProfileCourse(TimestampMixin, MajorProfileItemMixin, Base):
    __tablename__ = "major_profile_course"
    __table_args__ = (
        Index("ix_mpc_profile_id", "profile_id"),
        Index("ix_mpc_normalized_ref_id", "normalized_ref_id"),
        Index("ix_mpc_course_group", "course_group"),
    )

    course_group: Mapped[str] = mapped_column(Text, nullable=False)
    course_type: Mapped[str] = mapped_column(Text, nullable=False, default="course")

    profile: Mapped[MajorProfile] = relationship(back_populates="courses")
    normalized_ref: Mapped[NormalizedAssetRef] = relationship()


class MajorProfileCertificate(TimestampMixin, MajorProfileItemMixin, Base):
    __tablename__ = "major_profile_certificate"
    __table_args__ = (
        Index("ix_mpcert_profile_id", "profile_id"),
        Index("ix_mpcert_normalized_ref_id", "normalized_ref_id"),
    )

    certificate_type: Mapped[str] = mapped_column(Text, nullable=False, default="unknown")

    profile: Mapped[MajorProfile] = relationship(back_populates="certificates")
    normalized_ref: Mapped[NormalizedAssetRef] = relationship()


class MajorProfileContinuation(TimestampMixin, MajorProfileItemMixin, Base):
    __tablename__ = "major_profile_continuation"
    __table_args__ = (
        Index("ix_mpcont_profile_id", "profile_id"),
        Index("ix_mpcont_normalized_ref_id", "normalized_ref_id"),
    )

    profile: Mapped[MajorProfile] = relationship(back_populates="continuations")
    normalized_ref: Mapped[NormalizedAssetRef] = relationship()
# ---------------------------------------------------------------------------
# Pipeline B / B6 — Ability analysis domain tables.
# Schema frozen by docs/pipeline_b_contract_freeze.md §5.5-§5.11 and the
# writer contract docs/pipeline_b_b4_b6_contract_freeze.md §二.2 / §三.2.
# These tables are read-only via /v1 (open API) and written by
# nexus_app.domain_normalize.ability_analysis_writer.
# ---------------------------------------------------------------------------


class AbilityAnalysisProfile(TimestampMixin, Base):
    """Built-in ability-analysis model profile (PGSD etc.).

    System-seeded; not user-managed. P0 only ships the PGSD seed. New
    analysis models are added by inserting another (model_code,
    schema_version) row — never by mutating the existing PGSD row, so
    historical `occupational_ability_analysis.profile_id` stays valid.
    """
    __tablename__ = "ability_analysis_profile"
    __table_args__ = (
        UniqueConstraint(
            "model_code", "schema_version", name="uq_aap_model_schema",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    model_code: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    category_schema: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False,
    )
    code_pattern: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
    )
    relation_schema: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
    )
    detector_rules: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    initialized_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    initialized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )


class OccupationalAbilityAnalysis(TimestampMixin, Base):
    """Top-level analysis container — one row per normalized_asset_ref.

    Cascade-deleted children: tasks, work_contents, ability_items, relations,
    source_dataset links. dataset-level idempotency (§3.3) is enforced by
    deleting the existing analysis (cascade) before re-inserting; the FK
    `ondelete="CASCADE"` chain is what makes that safe.
    """
    __tablename__ = "occupational_ability_analysis"
    __table_args__ = (
        Index("ix_oaa_normalized_ref_id", "normalized_ref_id"),
        Index("ix_oaa_profile_id", "profile_id"),
        Index("ix_oaa_major", "major_name"),
        # dataset-level idempotency: only one analysis per normalized_ref.
        # Writer enforces this by upsert (delete-then-insert).
        UniqueConstraint("normalized_ref_id", name="uq_oaa_normalized_ref"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    normalized_ref_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("normalized_asset_ref.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("ability_analysis_profile.id"),
        nullable=False,
    )
    analysis_model: Mapped[str] = mapped_column(String(64), nullable=False)
    major_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    major_direction: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # B6 depends on B4 job_demand_dataset after merge; keep ORM FK in sync
    # with alembic so mapper relationship joins are deterministic.
    source_job_demand_dataset_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("job_demand_dataset.id", ondelete="SET NULL"),
        nullable=True,
    )
    task_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    work_content_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ability_item_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_summary: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
    )

    normalized_ref: Mapped[NormalizedAssetRef] = relationship()
    profile: Mapped[AbilityAnalysisProfile] = relationship()


class OccupationalWorkTask(TimestampMixin, Base):
    """One row per typical work task within an analysis."""
    __tablename__ = "occupational_work_task"
    __table_args__ = (
        Index("ix_owt_analysis_id", "analysis_id"),
        UniqueConstraint(
            "analysis_id", "task_code", name="uq_owt_analysis_task_code",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("occupational_ability_analysis.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_code: Mapped[str] = mapped_column(String(64), nullable=False)
    task_name: Mapped[str] = mapped_column(String(256), nullable=False)
    task_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # B6 writes `{}` here; B5 LLM extraction fills it later (decision 18/19).
    task_description_structured: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
    )
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    trace: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
    )


class OccupationalWorkContent(TimestampMixin, Base):
    """One row per work-content under a work task."""
    __tablename__ = "occupational_work_content"
    __table_args__ = (
        Index("ix_owc_task_id", "task_id"),
        UniqueConstraint(
            "analysis_id", "content_code", name="uq_owc_analysis_content_code",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("occupational_ability_analysis.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("occupational_work_task.id", ondelete="CASCADE"),
        nullable=False,
    )
    content_code: Mapped[str] = mapped_column(String(64), nullable=False)
    content_name: Mapped[str] = mapped_column(String(256), nullable=False)
    content_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    trace: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
    )


class OccupationalAbilityItem(TimestampMixin, Base):
    """One row per ability entry (P / G / S / D in PGSD).

    `work_content_id` is NULLable when the analysis profile declares
    `code_pattern[<category>].requires_work_content=false` — i.e. G / S / D
    in PGSD which hang directly off the task without a work_content level.
    """
    __tablename__ = "occupational_ability_item"
    __table_args__ = (
        Index("ix_oai_analysis_id", "analysis_id"),
        Index("ix_oai_task_id", "task_id"),
        Index("ix_oai_work_content_id", "work_content_id"),
        Index("ix_oai_category", "ability_major_category_code"),
        UniqueConstraint(
            "analysis_id", "ability_code", name="uq_oai_analysis_code",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("occupational_ability_analysis.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("occupational_work_task.id", ondelete="CASCADE"),
        nullable=False,
    )
    work_content_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("occupational_work_content.id", ondelete="CASCADE"),
        nullable=True,
    )
    ability_code: Mapped[str] = mapped_column(String(64), nullable=False)
    ability_major_category_code: Mapped[str] = mapped_column(String(16), nullable=False)
    ability_major_category_name: Mapped[str] = mapped_column(String(64), nullable=False)
    ability_sequence: Mapped[str] = mapped_column(String(64), nullable=False)
    ability_content: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_terms: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
    )
    # Confidence is set by future LLM passes; B6 leaves it NULL on initial write.
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    quality_flags: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
    )
    trace: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
    )


class OccupationalAbilityRelation(Base):
    """Graph-style edges between task / work_content / ability_item.

    `relation_type` is constrained to the whitelist documented at
    `pipeline_b_contract_freeze.md §5.10`:
        TASK_HAS_WORK_CONTENT
        WORK_CONTENT_REQUIRES_ABILITY
        ABILITY_DERIVED_FROM_JOB_REQUIREMENT  (B5 / later slice)
        ABILITY_RELATED_TO_SKILL              (B5 / later slice)
    B6 only writes the first two.
    """
    __tablename__ = "occupational_ability_relation"
    __table_args__ = (
        Index("ix_oar_analysis_id", "analysis_id"),
        Index("ix_oar_source", "source_type", "source_id"),
        Index("ix_oar_target", "target_type", "target_id"),
        Index("ix_oar_relation_type", "relation_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("occupational_ability_analysis.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
    )
    # Only created_at — relations are immutable evidence; no updated_at.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False,
    )


class AbilityAnalysisSourceDataset(Base):
    """Optional link: analysis → upstream job_demand_dataset(s) used as evidence.

    P0 default behavior: B6 writer does NOT populate this table (decision 7
    — ability analyses may exist without evidence). P1 / B7+ will write
    entries here when the analysis explicitly cites a job-demand dataset.
    The FK to `job_demand_dataset.id` is declared by the alembic migration
    so this worktree doesn't have a Python-import dependency on the B4
    SQLAlchemy model — at merge time B4 lands first, then B6 migration runs.
    """
    __tablename__ = "ability_analysis_source_dataset"
    __table_args__ = (
        Index("ix_aasd_analysis_id", "analysis_id"),
        Index("ix_aasd_dataset_id", "job_demand_dataset_id"),
        UniqueConstraint(
            "analysis_id", "job_demand_dataset_id", name="uq_aasd",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    analysis_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("occupational_ability_analysis.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_demand_dataset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("job_demand_dataset.id", ondelete="CASCADE"),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False,
    )



# ---------------------------------------------------------------------------
# Pipeline B B8 — CapabilityGraphStaging tables (build / node / edge)
# ---------------------------------------------------------------------------
# Schema source: docs/pipeline_b_contract_freeze.md §5.12 + design §七.
# These tables are the staging layer between domain reads (job_demand_* +
# occupational_*) and a future formal capability graph. CourseModule is
# reserved as a node_type / edge_type token in the design but NOT written
# in P0 (`pipeline_b_b4_b6_contract_freeze.md` doesn't gate B8, so the
# schema lives here without an extra freeze pass).
#
# Cascade chain: deleting a build wipes its nodes + edges. Deleting a node
# does NOT cascade to the build (edges already cascade-delete with the
# build) — preserves the build envelope so audit / quality_summary lookups
# still see a row even after node-level pruning.


class CapabilityGraphStagingBuild(TimestampMixin, Base):
    """One graph-construction batch over a normalized_asset_ref.

    `build_type` partitions the source data:
    - `job_demand`        — uses only job_demand_dataset + records + requirement_items
    - `ability_analysis`  — uses only occupational_* tables
    - `combined`          — uses both, plus ability_analysis_source_dataset links
    """
    __tablename__ = "capability_graph_staging_build"
    __table_args__ = (
        Index("ix_cgsb_normalized_ref_id", "normalized_ref_id"),
        Index("ix_cgsb_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    normalized_ref_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("normalized_asset_ref.id", ondelete="CASCADE"),
        nullable=False,
    )
    domain: Mapped[str] = mapped_column(String(40), nullable=False)
    build_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    quality_summary: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
    )


class CapabilityGraphStagingNode(TimestampMixin, Base):
    """A node candidate for the formal capability graph.

    `node_key` is the stable business key: uniqueness on
    (build_id, node_type, node_key) protects against duplicate inserts
    within the same build (per §5.12 uq_cgsn).
    """
    __tablename__ = "capability_graph_staging_node"
    __table_args__ = (
        UniqueConstraint(
            "build_id", "node_type", "node_key", name="uq_cgsn",
        ),
        Index("ix_cgsn_build_id", "build_id"),
        Index("ix_cgsn_type", "node_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    build_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("capability_graph_staging_build.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_type: Mapped[str] = mapped_column(String(64), nullable=False)
    node_key: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    canonical_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_table: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    properties: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
    )
    confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4), nullable=True,
    )


class CapabilityGraphStagingEdge(TimestampMixin, Base):
    """A directed edge connecting two staging nodes.

    `(build_id, source_node_id, target_node_id, edge_type)` is unique per
    §5.12 uq_cgse — same edge can't appear twice within one build.
    `edge_type` whitelist is enforced at the application layer (design
    §7.4); a future migration can add a CHECK constraint once the list
    stabilises beyond P0.
    """
    __tablename__ = "capability_graph_staging_edge"
    __table_args__ = (
        UniqueConstraint(
            "build_id", "source_node_id", "target_node_id", "edge_type",
            name="uq_cgse",
        ),
        Index("ix_cgse_build_id", "build_id"),
        Index("ix_cgse_edge_type", "edge_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    build_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("capability_graph_staging_build.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_node_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("capability_graph_staging_node.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_node_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("capability_graph_staging_node.id", ondelete="CASCADE"),
        nullable=False,
    )
    edge_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_table: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
    )
    confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4), nullable=True,
    )


# ---------------------------------------------------------------------------
# Evidence-grounded Knowledge Graph tables
# ---------------------------------------------------------------------------
# Schema source: docs/evidence_grounded_kg_implementation_plan.md.
# These tables store formal, evidence-bound graph builds over a complete
# normalized_asset_ref. CapabilityGraphStaging remains a separate Pipeline B
# staging model for job/ability graphs; do not mix the two schemas.


class KnowledgeGraphBuild(TimestampMixin, Base):
    """One Evidence-grounded KG build over a normalized_asset_ref."""

    __tablename__ = "knowledge_graph_build"
    __table_args__ = (
        Index(
            "ix_kgb_ref_profile_strategy",
            "normalized_ref_id", "graph_profile", "strategy_version",
        ),
        Index("ix_kgb_status_created", "status", "created_at"),
        Index(
            "uq_kgb_active_build_key",
            "normalized_ref_id",
            "graph_type",
            "graph_profile",
            "strategy_version",
            unique=True,
            postgresql_where=text("status <> 'deprecated'"),
            sqlite_where=text("status != 'deprecated'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    normalized_ref_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("normalized_asset_ref.id", ondelete="CASCADE"),
        nullable=False,
    )
    graph_type: Mapped[str] = mapped_column(
        String(64), nullable=False, default="evidence_grounded_kg",
    )
    graph_profile: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    source_chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fact_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_summary: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class KnowledgeGraphNode(TimestampMixin, Base):
    """Canonical entity node within a KnowledgeGraphBuild."""

    __tablename__ = "knowledge_graph_node"
    __table_args__ = (
        UniqueConstraint("graph_build_id", "node_key", name="uq_kgn_build_key"),
        Index("ix_kgn_build_type", "graph_build_id", "node_type"),
        Index("ix_kgn_normalized_ref_id", "normalized_ref_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    graph_build_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_graph_build.id", ondelete="CASCADE"),
        nullable=False,
    )
    normalized_ref_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("normalized_asset_ref.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_key: Mapped[str] = mapped_column(String(512), nullable=False)
    node_type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    properties: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)


class KnowledgeGraphFact(TimestampMixin, Base):
    """Qualified factual statement extracted from source chunks."""

    __tablename__ = "knowledge_graph_fact"
    __table_args__ = (
        Index("ix_kgf_build_type", "graph_build_id", "fact_type"),
        Index("ix_kgf_subject", "subject_node_id"),
        Index("ix_kgf_object_node", "object_node_id"),
        Index("ix_kgf_normalized_ref_id", "normalized_ref_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    graph_build_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_graph_build.id", ondelete="CASCADE"),
        nullable=False,
    )
    normalized_ref_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("normalized_asset_ref.id", ondelete="CASCADE"),
        nullable=False,
    )
    fact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_node_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_graph_node.id", ondelete="CASCADE"),
        nullable=False,
    )
    predicate: Mapped[str] = mapped_column(String(128), nullable=False)
    object_node_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("knowledge_graph_node.id", ondelete="SET NULL"),
        nullable=True,
    )
    object_literal: Mapped[str | None] = mapped_column(Text, nullable=True)
    qualifiers: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)


class KnowledgeGraphEdge(TimestampMixin, Base):
    """Normalized relation edge between two graph nodes."""

    __tablename__ = "knowledge_graph_edge"
    __table_args__ = (
        Index("ix_kge_build_type", "graph_build_id", "relation_type"),
        Index("ix_kge_nodes", "source_node_id", "target_node_id"),
        Index("ix_kge_normalized_ref_id", "normalized_ref_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    graph_build_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_graph_build.id", ondelete="CASCADE"),
        nullable=False,
    )
    normalized_ref_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("normalized_asset_ref.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_node_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_graph_node.id", ondelete="CASCADE"),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(String(128), nullable=False)
    target_node_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_graph_node.id", ondelete="CASCADE"),
        nullable=False,
    )
    properties: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False,
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)


class KnowledgeGraphMention(TimestampMixin, Base):
    """Entity mention anchored to a source chunk."""

    __tablename__ = "knowledge_graph_mention"
    __table_args__ = (
        Index("ix_kgm_build_entity", "graph_build_id", "entity_id"),
        Index("ix_kgm_chunk_id", "chunk_id"),
        Index("ix_kgm_normalized_ref_id", "normalized_ref_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    graph_build_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_graph_build.id", ondelete="CASCADE"),
        nullable=False,
    )
    normalized_ref_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("normalized_asset_ref.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_graph_node.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_chunk.id", ondelete="CASCADE"),
        nullable=False,
    )
    mention_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_block_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    locator: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)


class KnowledgeGraphEvidence(TimestampMixin, Base):
    """Evidence anchor for graph facts, edges, entities, or mentions."""

    __tablename__ = "knowledge_graph_evidence"
    __table_args__ = (
        Index("ix_kgev_chunk_id", "chunk_id"),
        Index("ix_kgev_fact", "graph_build_id", "fact_id"),
        Index("ix_kgev_edge", "graph_build_id", "edge_id"),
        Index("ix_kgev_entity", "graph_build_id", "entity_id"),
        Index("ix_kgev_mention", "graph_build_id", "mention_id"),
        Index("ix_kgev_normalized_ref_id", "normalized_ref_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    graph_build_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_graph_build.id", ondelete="CASCADE"),
        nullable=False,
    )
    normalized_ref_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("normalized_asset_ref.id", ondelete="CASCADE"),
        nullable=False,
    )
    fact_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("knowledge_graph_fact.id", ondelete="CASCADE"),
        nullable=True,
    )
    edge_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("knowledge_graph_edge.id", ondelete="CASCADE"),
        nullable=True,
    )
    entity_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("knowledge_graph_node.id", ondelete="CASCADE"),
        nullable=True,
    )
    mention_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("knowledge_graph_mention.id", ondelete="CASCADE"),
        nullable=True,
    )
    chunk_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_chunk.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_block_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    locator: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
