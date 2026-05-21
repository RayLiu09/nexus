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
    SKIPPED   = "skipped"


class ParseArtifactStatus(StrEnum):
    GENERATED = "generated"
    FAILED    = "failed"


class PipelineType(StrEnum):
    DOCUMENT = "document"
    RECORD   = "record"


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


class GovernanceResultStatus(StrEnum):
    AVAILABLE       = "available"
    REVIEW_REQUIRED = "review_required"


class IndexManifestStatus(StrEnum):
    PENDING = "pending"
    INDEXED = "indexed"
    FAILED  = "failed"


class PromptProfileStatus(StrEnum):
    ACTIVE   = "active"
    DISABLED = "disabled"
    ARCHIVED = "archived"


class AIGovernanceRunValidationStatus(StrEnum):
    SCHEMA_VALID      = "schema_valid"
    SCHEMA_INVALID    = "schema_invalid"
    POLICY_BLOCKED    = "policy_blocked"
    FAILED            = "failed"


class AIGovernanceRunAdoptionStatus(StrEnum):
    REVIEW_REQUIRED        = "review_required"
    PENDING_RULE_GUARDRAIL = "pending_rule_guardrail"
    AUTO_ADOPTED           = "auto_adopted"
    REJECTED               = "rejected"


class AuditEventType(StrEnum):
    # Ingest pipeline
    INGEST_BATCH_SUBMITTED          = "IngestBatchSubmitted"
    RAW_OBJECT_PERSISTED            = "RawObjectPersisted"
    INGEST_VALIDATE_COMPLETED       = "IngestValidateCompleted"
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
    # AI governance
    PROMPT_PROFILE_CREATED          = "PromptProfileCreated"
    PROMPT_PROFILE_UPDATED          = "PromptProfileUpdated"
    PROMPT_PROFILE_DISABLED         = "PromptProfileDisabled"
    AI_GOVERNANCE_RUN_CREATED       = "AIGovernanceRunCreated"
    AI_GOVERNANCE_RUN_FAILED        = "AIGovernanceRunFailed"
    GOVERNANCE_RULES_RELOADED       = "GovernanceRulesReloaded"
    # Consumption-side lineage foundation (P1)
    ASSET_VERSION_ACCESSED          = "AssetVersionAccessed"
    SEARCH_QUERY_EXECUTED           = "SearchQueryExecuted"
    QA_ANSWER_GENERATED             = "QAAnswerGenerated"
    # Governance rules and results (Week 4)
    GOVERNANCE_RULES_UPDATED            = "GovernanceRulesUpdated"
    GOVERNANCE_RESULT_CREATED       = "GovernanceResultCreated"
    VERSION_STATUS_TRANSITIONED     = "VersionStatusTransitioned"
    INDEX_MANIFEST_CREATED          = "IndexManifestCreated"
    # Knowledge Pipeline (Week 4 - TP-W4-05A)
    KNOWLEDGE_EMISSIONS_INFERRED    = "KnowledgeEmissionsInferred"
    KNOWLEDGE_CHUNKS_CREATED        = "KnowledgeChunksCreated"
    KNOWLEDGE_CHUNKS_INDEXED        = "KnowledgeChunksIndexed"


class ChunkingMode(StrEnum):
    PASSTHROUGH_TO_RAGFLOW = "passthrough_to_ragflow"
    NEXUS_EXTRACT          = "nexus_extract"


class ChunkType(StrEnum):
    PASSTHROUGH_DESCRIPTOR = "passthrough_descriptor"
    STRUCTURED_FIELD       = "structured_field"
    QA_PAIR                = "qa_pair"
    PROCESS_STEP           = "process_step"
    INDICATOR              = "indicator"
    CASE_SECTION           = "case_section"
    GRAPH_NODE             = "graph_node"
    TAG                    = "tag"


class ChunkingStrategy(StrEnum):
    PASSTHROUGH_TO_RAGFLOW = "passthrough_to_ragflow"
    STRUCTURED_DECOMPOSE   = "structured_decompose"
    QA_EXTRACT             = "qa_extract"
    PROCESS_STEP_EXTRACT   = "process_step_extract"
    INDICATOR_DECOMPOSE    = "indicator_decompose"
    CASE_DECOMPOSE         = "case_decompose"
    GRAPH_EXTRACT          = "graph_extract"
    TAG_DECOMPOSE          = "tag_decompose"


class SourceKind(StrEnum):
    EXTRACTED_FROM_NORMALIZED = "extracted_from_normalized"
    COAUTHORED_WITH_TEMPLATE  = "coauthored_with_template"
    MANUALLY_AUTHORED         = "manually_authored"


class EmbeddingStatus(StrEnum):
    PENDING  = "pending"
    EMBEDDED = "embedded"
    FAILED   = "failed"
