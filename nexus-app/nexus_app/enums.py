from enum import StrEnum


class AssetVersionStatus(StrEnum):
    PROCESSING = "processing"
    AVAILABLE = "available"
    REVIEW_REQUIRED = "review_required"
    ARCHIVED = "archived"
    DISABLED = "disabled"
    FAILED = "failed"


class IngestBatchStatus(StrEnum):
    SUBMITTED = "submitted"
    RAW_PERSISTED = "raw_persisted"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PARTIAL_FAILED = "partial_failed"
    FAILED = "failed"
    DUPLICATE_SKIPPED = "duplicate_skipped"


class RawObjectStatus(StrEnum):
    RAW_PERSISTED = "raw_persisted"
    CHECKSUM_FAILED = "checksum_failed"
    DUPLICATE_SKIPPED = "duplicate_skipped"
    FAILED = "failed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REVIEW_REQUIRED = "review_required"
    DEAD_LETTERED = "dead_lettered"
    CANCELLED = "cancelled"


class IndexStatus(StrEnum):
    NOT_INDEXED = "not_indexed"
    PENDING = "pending"
    BUILDING = "building"
    INDEXED = "indexed"
    FAILED = "failed"
    STALE = "stale"
    DISABLED = "disabled"


class AIAdoptionStatus(StrEnum):
    PENDING = "pending"
    AUTO_ADOPTED = "auto_adopted"
    PARTIALLY_ADOPTED = "partially_adopted"
    REVIEW_REQUIRED = "review_required"
    REJECTED = "rejected"
    OVERRIDDEN = "overridden"


class RuleSetStatus(StrEnum):
    DRAFT = "draft"
    VALIDATING = "validating"
    PUBLISHED = "published"
    DISABLED = "disabled"
    ARCHIVED = "archived"
    VALIDATION_FAILED = "validation_failed"


class PromptProfileStatus(StrEnum):
    DRAFT = "draft"
    VALIDATING = "validating"
    PUBLISHED = "published"
    ACTIVE = "active"
    DISABLED = "disabled"
    ARCHIVED = "archived"
    VALIDATION_FAILED = "validation_failed"


class PrincipalStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    ARCHIVED = "archived"


class DataSourceStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"


class DataSourceType(StrEnum):
    FILE_UPLOAD = "file_upload"
    NAS = "nas"
    CRAWLER = "crawler"
    DATABASE = "database"
    WEBHOOK = "webhook"


class UserRole(StrEnum):
    PLATFORM_DATA_ADMIN = "platform_data_admin"
    BUSINESS_EXPERT = "business_expert"
    OPS = "ops"
    API_CALLER = "api_caller"
