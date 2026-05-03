from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from nexus_app.enums import (
    DataSourceStatus,
    DataSourceType,
    IngestBatchStatus,
    PrincipalStatus,
    RawObjectStatus,
    UserRole,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class OrgUnitCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    parent_id: str | None = None
    status: PrincipalStatus = PrincipalStatus.ACTIVE


class OrgUnitRead(ORMModel):
    id: str
    code: str
    name: str
    parent_id: str | None
    status: PrincipalStatus
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
    caller_key: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=128)
    org_scope: list[str] = Field(default_factory=list)
    permission_scope: list[str] = Field(default_factory=list)
    owner_user_id: str | None = None
    status: PrincipalStatus = PrincipalStatus.ACTIVE


class ApiCallerRead(ORMModel):
    id: str
    caller_key: str
    name: str
    org_scope: list[str]
    permission_scope: list[str]
    owner_user_id: str | None
    status: PrincipalStatus
    created_at: datetime
    updated_at: datetime


class DataSourceCreate(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=128)
    source_type: DataSourceType
    owner_user_id: str | None = None
    org_scope_hint: list[str] = Field(default_factory=list)
    default_governance_hints: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None
    status: DataSourceStatus = DataSourceStatus.ENABLED


class DataSourceRead(ORMModel):
    id: str
    code: str
    name: str
    source_type: DataSourceType
    status: DataSourceStatus
    owner_user_id: str | None
    org_scope_hint: list[str]
    default_governance_hints: dict[str, Any]
    description: str | None
    created_at: datetime
    updated_at: datetime


class IngestBatchCreate(BaseModel):
    data_source_id: str
    idempotency_key: str = Field(min_length=1, max_length=128)
    source_type: DataSourceType
    submitted_by_user_id: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    status: IngestBatchStatus = IngestBatchStatus.SUBMITTED


class IngestBatchRead(ORMModel):
    id: str
    data_source_id: str
    idempotency_key: str
    source_type: DataSourceType
    status: IngestBatchStatus
    submitted_by_user_id: str | None
    summary: dict[str, Any]
    created_at: datetime
    updated_at: datetime


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
    metadata_summary: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class RuntimeStateRead(BaseModel):
    api: str
    database: str
    workers: str
    queue: str
    recent_error: str | None = None
