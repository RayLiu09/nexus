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
    OPEN             = "open"
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
    PARTIAL   = "partial"


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


class GovernanceRulesVersionStatus(StrEnum):
    ACTIVE   = "active"
    ARCHIVED = "archived"


class GovernancePromptTemplateStatus(StrEnum):
    ACTIVE   = "active"
    ARCHIVED = "archived"
    DISABLED = "disabled"


class GovernanceTaskType(StrEnum):
    CLASSIFICATION              = "classification"
    LEVEL_ASSESSMENT            = "level_assessment"
    TAGGING                     = "tagging"
    QUALITY_SCORING             = "quality_scoring"
    KNOWLEDGE_TYPE_INFERENCE    = "knowledge_type_inference"


class IndexManifestStatus(StrEnum):
    PENDING = "pending"
    INDEXED = "indexed"
    STALE   = "stale"
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
    INGEST_VALIDATE_FAILED          = "IngestValidateFailed"
    # Pipeline B structured_parse stage (B1.3) — emitted on successful xlsx /
    # (future) csv parse. Failures use PIPELINE_FAILED with error_code so
    # operators don't have to disjoin on the audit event name.
    STRUCTURED_PARSE_COMPLETED      = "StructuredParseCompleted"
    # Pipeline B profile_detect stage (B2.3) — emitted on every successful
    # detection (high and low confidence). REVIEW_REQUIRED is emitted in
    # addition (not in place of) DETECTED when the detector confidence
    # falls below the auto-admit threshold or the record_type is a
    # `_candidate` / `generic_table_dataset` variant.
    RECORD_PROFILE_DETECTED         = "RecordProfileDetected"
    RECORD_PROFILE_REVIEW_REQUIRED  = "RecordProfileReviewRequired"
    # Pipeline B domain_normalize stage (B4 / B6 共用接缝) — emitted by
    # `dispatch_domain_normalize` after the per-domain writer (job_demand_writer
    # / ability_analysis_writer) returns. The writer-specific events
    # (JOB_DEMAND_DATASET_PERSISTED / ABILITY_ANALYSIS_PERSISTED / ...) are
    # written in addition to these dispatcher-level ones, so reviewers can
    # disjoin on either the high-level stage or the domain-specific entity.
    DOMAIN_NORMALIZE_COMPLETED      = "DomainNormalizeCompleted"
    DOMAIN_NORMALIZE_FAILED         = "DomainNormalizeFailed"
    # Pipeline B B4 — job_demand writer-specific events (per
    # docs/pipeline_b_b4_b6_contract_freeze.md §七). Emitted IN ADDITION TO
    # DOMAIN_NORMALIZE_COMPLETED so operators can disjoin on the high-level
    # stage OR the domain-specific entity that landed.
    JOB_DEMAND_DATASET_PERSISTED    = "JobDemandDatasetPersisted"
    JOB_DEMAND_RECORDS_PERSISTED    = "JobDemandRecordsPersisted"
    # Pipeline B B6 — ability_analysis writer events (same disjoin rationale
    # as B4 above).
    ABILITY_ANALYSIS_PERSISTED      = "AbilityAnalysisPersisted"
    ABILITY_ITEMS_PERSISTED         = "AbilityItemsPersisted"
    ABILITY_ITEMS_REJECTED          = "AbilityItemsRejected"
    # Pipeline B B5.2 — knowledge_unit extraction outcome. One event per
    # job_demand_dataset that ran through the LLM extraction service. Carries
    # rule_set_id + prompt_profile_id + per-record counts so the audit alone
    # is enough to reproduce the decision (re-running LLM not required).
    REQUIREMENT_ITEMS_EXTRACTED     = "RequirementItemsExtracted"
    # Pipeline B B5.3 — body_markdown render outcome. One event per
    # normalized_record (job_demand OR ability_analysis) that ran through
    # the renderer. Records render_strategy (LLM vs deterministic),
    # skeleton validation, fallback_reason, and the record_body_hash that
    # drove the cache lookup.
    BODY_MARKDOWN_RENDERED          = "BodyMarkdownRendered"
    # Pipeline B B5.4 — task_description_structured LLM outcome. One event
    # per occupational_ability_analysis. Tasks structured / rejected counts
    # let reviewers see whether the B6 placeholder `{}` has been filled in
    # at all.
    TASK_DESCRIPTIONS_STRUCTURED    = "TaskDescriptionsStructured"
    # Pipeline B B7 — PGSD ability_analysis governance outcome. One event
    # per analysis governance run. Carries blocking/warning counts + the
    # governance_result.id so the audit can be joined back to the persisted
    # decision row.
    ABILITY_ANALYSIS_GOVERNED       = "AbilityAnalysisGoverned"
    # Pipeline B B8 — CapabilityGraphStaging materialization. One event per
    # `build_capability_staging` call. Carries the build_id + counts so the
    # audit alone is enough to reproduce the build outcome.
    CAPABILITY_GRAPH_STAGING_GENERATED = "CapabilityGraphStagingGenerated"
    # Pipeline B PD — operator-maintained major distribution structured rows.
    MAJOR_DISTRIBUTION_RECORD_UPDATED = "MajorDistributionRecordUpdated"
    MAJOR_DISTRIBUTION_RECORD_DELETED = "MajorDistributionRecordDeleted"
    CROSS_SOURCE_DUPLICATE_DETECTED = "CrossSourceDuplicateDetected"
    VERSION_STATUS_CHANGED          = "VersionStatusChanged"
    PIPELINE_FAILED                 = "PipelineFailed"
    # Asset lifecycle
    ASSET_VERSION_ARCHIVED          = "AssetVersionArchived"
    # Data source management
    DATA_SOURCE_CREATED             = "DataSourceCreated"
    DATA_SOURCE_STATUS_CHANGED      = "DataSourceStatusChanged"
    DATA_SOURCE_DELETED             = "DataSourceDeleted"
    # API caller management
    API_CALLER_CREATED              = "ApiCallerCreated"
    API_CALLER_UPDATED              = "ApiCallerUpdated"
    API_CALLER_REVOKED              = "ApiCallerRevoked"
    # Auth (JWT user session)
    USER_LOGIN_SUCCEEDED            = "UserLoginSucceeded"
    USER_LOGIN_FAILED               = "UserLoginFailed"
    USER_LOGIN_LOCKED               = "UserLoginLocked"
    USER_LOGOUT                     = "UserLogout"
    TOKEN_REFRESHED                 = "TokenRefreshed"
    TOKEN_REFRESH_FAILED            = "TokenRefreshFailed"
    # Job control (operator actions)
    JOB_RETRIED                     = "JobRetried"
    JOB_CANCELLED                   = "JobCancelled"
    # AI governance
    PROMPT_PROFILE_CREATED          = "PromptProfileCreated"
    PROMPT_PROFILE_UPDATED          = "PromptProfileUpdated"
    PROMPT_PROFILE_DISABLED         = "PromptProfileDisabled"
    AI_GOVERNANCE_RUN_CREATED       = "AIGovernanceRunCreated"
    AI_GOVERNANCE_RUN_FAILED        = "AIGovernanceRunFailed"
    GOVERNANCE_RULES_RELOADED       = "GovernanceRulesReloaded"
    # Consumption-side lineage foundation
    ASSET_VERSION_ACCESSED          = "AssetVersionAccessed"
    SEARCH_QUERY_EXECUTED           = "SearchQueryExecuted"
    QA_ANSWER_GENERATED             = "QAAnswerGenerated"
    # Governance rules and results (Week 4)
    GOVERNANCE_RULES_UPDATED            = "GovernanceRulesUpdated"
    GOVERNANCE_RULES_RECOMPUTE_REQUESTED = "GovernanceRulesRecomputeRequested"
    GOVERNANCE_RESULT_CREATED       = "GovernanceResultCreated"
    VERSION_STATUS_TRANSITIONED     = "VersionStatusTransitioned"
    INDEX_MANIFEST_CREATED          = "IndexManifestCreated"
    # Knowledge Pipeline (Week 4 - TP-W4-05A)
    KNOWLEDGE_EMISSIONS_INFERRED    = "KnowledgeEmissionsInferred"
    KNOWLEDGE_CHUNKS_CREATED        = "KnowledgeChunksCreated"
    KNOWLEDGE_CHUNKS_INDEXED        = "KnowledgeChunksIndexed"
    # Knowledge / Index pipeline SKIPS — visible audit trail for assets that
    # passed governance but never made it to the knowledge base (§13). Without
    # these, operators see `status=available` + `index_admission=True` and
    # incorrectly assume the asset is searchable.
    KNOWLEDGE_CHUNKING_SKIPPED      = "KnowledgeChunkingSkipped"
    INDEX_SUBMIT_SKIPPED            = "IndexSubmitSkipped"
    # Governance rules version management
    GOVERNANCE_RULES_VERSION_CREATED   = "GovernanceRulesVersionCreated"
    GOVERNANCE_RULES_VERSION_ARCHIVED  = "GovernanceRulesVersionArchived"
    # Governance prompt template management
    GOVERNANCE_PROMPT_TEMPLATE_CREATED   = "GovernancePromptTemplateCreated"
    GOVERNANCE_PROMPT_TEMPLATE_UPDATED   = "GovernancePromptTemplateUpdated"
    GOVERNANCE_PROMPT_TEMPLATE_ARCHIVED  = "GovernancePromptTemplateArchived"
    GOVERNANCE_PROMPT_TEMPLATE_DISABLED  = "GovernancePromptTemplateDisabled"


class AssetAccessType(StrEnum):
    """`ASSET_VERSION_ACCESSED.summary.access_type` discriminator.

    Each value identifies which `/open/v1` read endpoint emitted the audit
    event. Used by the consumption-side lineage view to reconstruct how an
    upstream application reached a given normalized asset.
    """
    ASSET_DETAIL       = "asset_detail"
    VERSION_LIST       = "version_list"
    NORMALIZED_REF     = "normalized_ref"
    GOVERNANCE_RESULT  = "governance_result"
    KNOWLEDGE_CHUNK    = "knowledge_chunk"
    RAW_DOWNLOAD       = "raw_download"
    CHUNK_LIST         = "chunk_list"


class ChunkingMode(StrEnum):
    # Legacy alias retained for historical configs. New semantic RAG chunks are
    # built locally by Nexus and do not imply RAGFlow submission.
    PASSTHROUGH_TO_RAGFLOW = "passthrough_to_ragflow"
    NEXUS_SEMANTIC         = "nexus_semantic"
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
    # Slice 2 — semantic-repack produces one SEMANTIC_BLOCK per coherent unit.
    # Replaces the legacy PASSTHROUGH_DESCRIPTOR path: blocks no longer go to
    # RAGFlow as one opaque whole-document chunk; instead Nexus does semantic
    # segmentation on normalized blocks and emits N retrieval-grade chunks.
    SEMANTIC_BLOCK         = "semantic_block"
    # Record pipeline — one structured row per chunk (e.g. job_demand record).
    # Used by KTs whose governance_rules_v2.json declares
    # ``chunking_mode=row_per_chunk`` (e.g. ``structured_record_table``).
    STRUCTURED_RECORD_ROW  = "structured_record_row"


class ChunkingStrategy(StrEnum):
    PASSTHROUGH_TO_RAGFLOW = "passthrough_to_ragflow"
    STRUCTURED_DECOMPOSE   = "structured_decompose"
    QA_EXTRACT             = "qa_extract"
    PROCESS_STEP_EXTRACT   = "process_step_extract"
    INDICATOR_DECOMPOSE    = "indicator_decompose"
    CASE_DECOMPOSE         = "case_decompose"
    GRAPH_EXTRACT          = "graph_extract"
    TAG_DECOMPOSE          = "tag_decompose"
    # Slice 2 — strategy code for semantic-repack output.
    SEMANTIC_REPACK        = "semantic_repack"
    # Record pipeline — explodes a record_body into one chunk per row.
    ROW_DECOMPOSE          = "row_decompose"
    # Pipeline A major_profile — one semantic chunk per business section.
    MAJOR_PROFILE_DECOMPOSE = "major_profile_decompose"


class SourceKind(StrEnum):
    EXTRACTED_FROM_NORMALIZED = "extracted_from_normalized"
    COAUTHORED_WITH_TEMPLATE  = "coauthored_with_template"
    MANUALLY_AUTHORED         = "manually_authored"


class EmbeddingStatus(StrEnum):
    PENDING  = "pending"
    EMBEDDED = "embedded"
    FAILED   = "failed"
