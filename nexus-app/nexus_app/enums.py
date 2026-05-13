from enum import StrEnum


class OrgUnitStatus(StrEnum):
    ACTIVE   = "active"
    DISABLED = "disabled"


class PrincipalStatus(StrEnum):
    ACTIVE   = "active"
    DISABLED = "disabled"


class UserRole(StrEnum):
    PLATFORM_DATA_ADMIN = "platform_data_admin"
    BUSINESS_EXPERT     = "business_expert"
    OPS                 = "ops"
    API_CALLER          = "api_caller"


class DataSourceStatus(StrEnum):
    ENABLED  = "enabled"
    DISABLED = "disabled"
    ERROR    = "error"


class DataSourceType(StrEnum):
    FILE_UPLOAD = "file_upload"
    NAS         = "nas"
    CRAWLER     = "crawler"
    DATABASE    = "database"
    WEBHOOK     = "webhook"


class IngestBatchStatus(StrEnum):
    SUBMITTED        = "submitted"
    RAW_PERSISTED    = "raw_persisted"
    PROCESSING       = "processing"
    COMPLETED        = "completed"
    PARTIAL_FAILED   = "partial_failed"
    FAILED           = "failed"
    DUPLICATE_SKIPPED = "duplicate_skipped"


class RawObjectStatus(StrEnum):
    RAW_PERSISTED     = "raw_persisted"
    CHECKSUM_FAILED   = "checksum_failed"
    DUPLICATE_SKIPPED = "duplicate_skipped"
    FAILED            = "failed"


class JobStatus(StrEnum):
    QUEUED        = "queued"
    RUNNING       = "running"
    SUCCEEDED     = "succeeded"
    FAILED        = "failed"
    REVIEW_REQUIRED = "review_required"
    DEAD_LETTERED = "dead_lettered"
    CANCELLED     = "cancelled"


class JobType(StrEnum):
    INGEST_PROCESS = "ingest_process"


class StageStatus(StrEnum):
    """Status values valid for a single pipeline stage execution record."""
    RUNNING   = "running"
    SUCCEEDED = "succeeded"
    FAILED    = "failed"


class ParseArtifactStatus(StrEnum):
    GENERATED = "generated"
    FAILED    = "failed"


class NormalizedType(StrEnum):
    DOCUMENT = "document"
    RECORD   = "record"


class NormalizedAssetRefStatus(StrEnum):
    GENERATED  = "generated"
    FAILED     = "failed"
    DEPRECATED = "deprecated"


class AssetKind(StrEnum):
    DOCUMENT = "document"
    RECORD   = "record"


class AssetVersionStatus(StrEnum):
    PROCESSING      = "processing"
    AVAILABLE       = "available"
    REVIEW_REQUIRED = "review_required"
    ARCHIVED        = "archived"
    DISABLED        = "disabled"
    FAILED          = "failed"


class IndexStatus(StrEnum):
    NOT_INDEXED = "not_indexed"
    PENDING     = "pending"
    BUILDING    = "building"
    INDEXED     = "indexed"
    FAILED      = "failed"
    STALE       = "stale"
    DISABLED    = "disabled"


class AIAdoptionStatus(StrEnum):
    PENDING           = "pending"
    AUTO_ADOPTED      = "auto_adopted"
    PARTIALLY_ADOPTED = "partially_adopted"
    REVIEW_REQUIRED   = "review_required"
    REJECTED          = "rejected"
    OVERRIDDEN        = "overridden"


class RuleSetStatus(StrEnum):
    ACTIVE   = "active"
    DISABLED = "disabled"


class PromptProfileStatus(StrEnum):
    ACTIVE   = "active"
    DISABLED = "disabled"
    ARCHIVED = "archived"


class AuditEventType(StrEnum):
    # Ingest pipeline
    INGEST_BATCH_SUBMITTED          = "IngestBatchSubmitted"
    RAW_OBJECT_PERSISTED            = "RawObjectPersisted"
    CROSS_SOURCE_DUPLICATE_DETECTED = "CrossSourceDuplicateDetected"
    VERSION_STATUS_CHANGED          = "VersionStatusChanged"
    PIPELINE_FAILED                 = "PipelineFailed"
    # Asset lifecycle
    ASSET_VERSION_ARCHIVED          = "AssetVersionArchived"
    # Data source management
    DATA_SOURCE_CREATED             = "DataSourceCreated"
    DATA_SOURCE_STATUS_CHANGED      = "DataSourceStatusChanged"
    # API caller management
    API_CALLER_CREATED              = "ApiCallerCreated"
    API_CALLER_REVOKED              = "ApiCallerRevoked"
