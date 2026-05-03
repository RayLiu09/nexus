from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexus_app.database import Base
from nexus_app.enums import (
    DataSourceStatus,
    DataSourceType,
    IngestBatchStatus,
    PrincipalStatus,
    RawObjectStatus,
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
    status: Mapped[PrincipalStatus] = mapped_column(
        Enum(PrincipalStatus, values_callable=lambda enum: [item.value for item in enum]),
        default=PrincipalStatus.ACTIVE,
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
    status: Mapped[PrincipalStatus] = mapped_column(
        Enum(PrincipalStatus, values_callable=lambda enum: [item.value for item in enum]),
        default=PrincipalStatus.ACTIVE,
        nullable=False,
    )
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
    org_scope_hint: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    default_governance_hints: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
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
    submitted_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user_account.id"), nullable=True
    )
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    data_source: Mapped[DataSource] = relationship()
    submitted_by_user: Mapped[UserAccount | None] = relationship()


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
    metadata_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    batch: Mapped[IngestBatch] = relationship()
    data_source: Mapped[DataSource] = relationship()
