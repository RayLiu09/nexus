from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus_app.database import Base
from nexus_app.enums import (
    AuditEventType,
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
    RawObjectStatus,
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

    org_unit: Mapped[OrgUnit | None] = relationship()


class ApiCaller(TimestampMixin, Base):
    __tablename__ = "api_caller"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    caller_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    org_scope: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    permission_scope: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

    data_source: Mapped[DataSource] = relationship()
    owner_user: Mapped[UserAccount | None] = relationship()


class RawObject(TimestampMixin, Base):
    __tablename__ = "raw_object"
    __table_args__ = (
        UniqueConstraint("data_source_id", "checksum", name="uq_raw_object_source_checksum"),
        Index("ix_raw_object_batch_id", "batch_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    batch_id: Mapped[str] = mapped_column(String(36), ForeignKey("ingest_batch.id"), nullable=False)
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
        Index("idx_job_lock_expiry", "status", "lock_expires_at"),
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
    priority: Mapped[int] = mapped_column(default=100, nullable=False)
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
    metadata_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

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


class DocumentAsset(TimestampMixin, Base):
    __tablename__ = "document_asset"
    __table_args__ = (
        UniqueConstraint("data_source_id", "source_object_key", name="uq_document_asset_source_key"),
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


class DocumentVersion(TimestampMixin, Base):
    __tablename__ = "document_version"
    __table_args__ = (
        UniqueConstraint("asset_id", "version_no", name="uq_document_version_asset_no"),
        Index("ix_document_version_asset_status", "asset_id", "version_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("document_asset.id"), nullable=False
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

    asset: Mapped[DocumentAsset] = relationship()
    raw_object: Mapped[RawObject] = relationship()


class ParseArtifact(TimestampMixin, Base):
    __tablename__ = "parse_artifact"
    __table_args__ = (Index("ix_parse_artifact_raw_object_id", "raw_object_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    raw_object_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("raw_object.id"), nullable=False
    )
    document_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("document_version.id"), nullable=True
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
    document_version: Mapped[DocumentVersion | None] = relationship()


class NormalizedAssetRef(TimestampMixin, Base):
    __tablename__ = "normalized_asset_ref"
    __table_args__ = (
        Index("ix_normalized_asset_ref_version_id", "version_id"),
        Index("ix_normalized_asset_ref_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("document_version.id"), nullable=False
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
    metadata_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    version: Mapped[DocumentVersion] = relationship()
