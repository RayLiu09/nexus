import type {
  DataSource,
  IngestBatch,
  Job,
  JobStage,
  RawObject,
  Asset,
  AssetVersion,
  NormalizedAssetRef,
  AssetDetail,
  AIGovernanceRun,
  AuditLog,
  RuntimeState,
  OrgUnit,
  UserAccount,
} from "./api";

// ── Runtime ────────────────────────────────────────────────────

export const MOCK_RUNTIME: RuntimeState = {
  api: "healthy",
  database: "connected",
  workers: "3/4 active",
  queue: "idle (0 pending)",
  recent_error: null,
};

// ── Org Units ──────────────────────────────────────────────────

export const MOCK_ORG_UNITS: OrgUnit[] = [
  { id: "ou-001", code: "jwc", name: "教务处", parent_id: null, status: "active", created_at: "2025-01-10T08:00:00Z", updated_at: "2026-05-15T10:00:00Z" },
  { id: "ou-002", code: "itc", name: "信息中心", parent_id: null, status: "active", created_at: "2025-01-10T08:00:00Z", updated_at: "2026-05-20T14:30:00Z" },
  { id: "ou-003", code: "rsb", name: "人事部", parent_id: null, status: "active", created_at: "2025-02-01T09:00:00Z", updated_at: "2026-04-18T11:00:00Z" },
];

// ── Users ──────────────────────────────────────────────────────

export const MOCK_USERS: UserAccount[] = [
  { id: "u-001", username: "zhangsan", display_name: "张三", role: "admin", org_unit_id: "ou-001", email: "zhangsan@edu.cn", status: "active", created_at: "2025-01-10T08:00:00Z", updated_at: "2026-06-01T09:00:00Z" },
  { id: "u-002", username: "lisi", display_name: "李四", role: "operator", org_unit_id: "ou-002", email: "lisi@edu.cn", status: "active", created_at: "2025-02-15T10:00:00Z", updated_at: "2026-05-28T16:00:00Z" },
  { id: "u-003", username: "wangwu", display_name: "王五", role: "viewer", org_unit_id: "ou-003", email: "wangwu@edu.cn", status: "active", created_at: "2025-03-01T08:30:00Z", updated_at: "2026-05-10T11:00:00Z" },
];

// ── Data Sources ───────────────────────────────────────────────

export const MOCK_DATA_SOURCES: DataSource[] = [
  {
    id: "ds-001", code: "ds_teaching_nas", name: "教学资源 NAS", source_type: "nas",
    status: "active", owner_user_id: "u-001", org_scope_hint: ["教务处"],
    default_governance_hints: { auto_adopt: true, confidence_threshold: 0.85 },
    connection_config: { cfg_mount_path: "/mnt/nas/teaching-resources", cfg_scan_pattern: "**/*.pdf,**/*.docx", cfg_nas_host: "192.168.1.100", cfg_nas_port: "445", cfg_nas_username: "nexus_reader" },
    description: "教务处历年教学大纲、课件、试卷等教学资源", created_at: "2025-06-01T08:00:00Z", updated_at: "2026-05-28T10:00:00Z",
  },
  {
    id: "ds-002", code: "ds_crawler_policy", name: "政策文件爬虫", source_type: "crawler",
    status: "active", owner_user_id: "u-001", org_scope_hint: ["教务处", "信息中心"],
    default_governance_hints: { auto_adopt: true, confidence_threshold: 0.80 },
    connection_config: { cfg_target_url: "https://www.gov.cn/zhengce/", cfg_schedule_cron: "0 2 * * *" },
    description: "教育部、科技部等政策文件自动抓取", created_at: "2025-07-15T09:00:00Z", updated_at: "2026-05-25T14:00:00Z",
  },
  {
    id: "ds-003", code: "ds_hr_db", name: "人力资源数据库", source_type: "database",
    status: "active", owner_user_id: "u-003", org_scope_hint: ["人事部"],
    default_governance_hints: { auto_adopt: false, confidence_threshold: 0.90, level: "L3" },
    connection_config: { cfg_connection_string: "postgresql://reader:***@10.0.1.50:5432/hr", cfg_query: "SELECT * FROM employee_training WHERE updated_at > :last_sync", cfg_schedule_cron: "0 */6 * * *" },
    description: "员工培训档案与考核记录", created_at: "2025-08-01T10:00:00Z", updated_at: "2026-05-20T09:00:00Z",
  },
  {
    id: "ds-004", code: "ds_webhook_api", name: "第三方 API 推送", source_type: "webhook",
    status: "active", owner_user_id: "u-002", org_scope_hint: ["信息中心"],
    default_governance_hints: { auto_adopt: true, confidence_threshold: 0.75 },
    connection_config: { cfg_webhook_secret: "whsec_***", cfg_allowed_ips: "10.0.0.0/8,172.16.0.0/12" },
    description: "合作院校通过 API 推送共享资源", created_at: "2025-09-10T11:00:00Z", updated_at: "2026-05-18T16:00:00Z",
  },
  {
    id: "ds-005", code: "ds_local_upload", name: "本地文件上传", source_type: "file_upload",
    status: "active", owner_user_id: "u-001", org_scope_hint: ["教务处"],
    default_governance_hints: { auto_adopt: true, confidence_threshold: 0.80 },
    connection_config: null,
    description: "教师手动上传课件、讲义等文档", created_at: "2025-10-01T08:00:00Z", updated_at: "2026-05-15T08:00:00Z",
  },
];

// ── Ingest Batches ─────────────────────────────────────────────

export const MOCK_BATCHES: IngestBatch[] = [
  {
    id: "batch-001", data_source_id: "ds-001", idempotency_key: "idem-nas-20260601-001",
    source_type: "nas", status: "completed", submitted_by_user_id: "u-001",
    summary: { filename: "高等数学教学大纲-v3.2.pdf", package_type: "single", file_count: 1, total_size_bytes: 2457600 },
    created_at: "2026-06-01T08:00:00Z", updated_at: "2026-06-01T08:03:15Z",
  },
  {
    id: "batch-002", data_source_id: "ds-002", idempotency_key: "idem-crawler-20260601-001",
    source_type: "crawler", status: "completed", submitted_by_user_id: "u-001",
    summary: { filename: "教育部2026年工作要点.pdf", package_type: "single", file_count: 1, total_size_bytes: 1890304 },
    created_at: "2026-06-01T08:30:00Z", updated_at: "2026-06-01T08:32:45Z",
  },
  {
    id: "batch-003", data_source_id: "ds-003", idempotency_key: "idem-db-20260601-001",
    source_type: "database", status: "processing", submitted_by_user_id: "u-003",
    summary: { filename: "员工培训记录-2026Q2.xlsx", package_type: "single", file_count: 1, total_size_bytes: 524288 },
    created_at: "2026-06-01T09:00:00Z", updated_at: "2026-06-01T09:15:00Z",
  },
  {
    id: "batch-004", data_source_id: "ds-005", idempotency_key: "idem-upload-20260601-001",
    source_type: "file_upload", status: "completed", submitted_by_user_id: "u-001",
    summary: { filename: "线性代数讲义-第六章.pdf", package_type: "single", file_count: 1, total_size_bytes: 1048576 },
    created_at: "2026-05-31T14:00:00Z", updated_at: "2026-05-31T14:02:30Z",
  },
  {
    id: "batch-005", data_source_id: "ds-004", idempotency_key: "idem-webhook-20260530-001",
    source_type: "webhook", status: "failed", submitted_by_user_id: "u-002",
    summary: { filename: "合作院校共享资源包.zip", package_type: "archive", file_count: 15, total_size_bytes: 15728640 },
    created_at: "2026-05-30T10:00:00Z", updated_at: "2026-05-30T10:05:00Z",
  },
];

// ── Raw Objects ────────────────────────────────────────────────

export const MOCK_RAW_OBJECTS: RawObject[] = [
  {
    id: "raw-001", batch_id: "batch-001", data_source_id: "ds-001", source_type: "nas",
    source_uri: "/mnt/nas/teaching-resources/math/advanced-math-v3.2.pdf",
    object_uri: "s3://nexus-raw/raw-001.pdf", checksum: "sha256:a1b2c3d4e5f6...", mime_type: "application/pdf",
    size_bytes: 2457600, status: "completed", metadata_summary: { pages: 42, language: "zh-CN" },
    created_at: "2026-06-01T08:00:00Z", updated_at: "2026-06-01T08:01:00Z",
  },
  {
    id: "raw-002", batch_id: "batch-002", data_source_id: "ds-002", source_type: "crawler",
    source_uri: "https://www.gov.cn/zhengce/2026-06/01/content_xxx.html",
    object_uri: "s3://nexus-raw/raw-002.html", checksum: "sha256:b2c3d4e5f6a7...", mime_type: "text/html",
    size_bytes: 1890304, status: "completed", metadata_summary: { sections: 8, language: "zh-CN" },
    created_at: "2026-06-01T08:30:00Z", updated_at: "2026-06-01T08:31:00Z",
  },
  {
    id: "raw-003", batch_id: "batch-003", data_source_id: "ds-003", source_type: "database",
    source_uri: null,
    object_uri: "s3://nexus-raw/raw-003.xlsx", checksum: "sha256:c3d4e5f6a7b8...", mime_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    size_bytes: 524288, status: "processing", metadata_summary: { records: 1280, columns: 18 },
    created_at: "2026-06-01T09:00:00Z", updated_at: "2026-06-01T09:10:00Z",
  },
  {
    id: "raw-004", batch_id: "batch-004", data_source_id: "ds-005", source_type: "file_upload",
    source_uri: null,
    object_uri: "s3://nexus-raw/raw-004.pdf", checksum: "sha256:d4e5f6a7b8c9...", mime_type: "application/pdf",
    size_bytes: 1048576, status: "completed", metadata_summary: { pages: 28, language: "zh-CN" },
    created_at: "2026-05-31T14:00:00Z", updated_at: "2026-05-31T14:01:00Z",
  },
];

// ── Jobs ───────────────────────────────────────────────────────

export const MOCK_JOB_STAGES: Record<string, JobStage[]> = {
  "job-001": [
    { id: "stg-001-1", job_id: "job-001", stage_name: "ingest_validate", status: "completed", started_at: "2026-06-01T08:00:01Z", finished_at: "2026-06-01T08:00:15Z", failure_reason: null, detail: { result: "pass" }, created_at: "2026-06-01T08:00:01Z", updated_at: "2026-06-01T08:00:15Z" },
    { id: "stg-001-2", job_id: "job-001", stage_name: "assetize", status: "completed", started_at: "2026-06-01T08:00:16Z", finished_at: "2026-06-01T08:00:30Z", failure_reason: null, detail: { asset_id: "asset-001", version_id: "ver-001" }, created_at: "2026-06-01T08:00:16Z", updated_at: "2026-06-01T08:00:30Z" },
    { id: "stg-001-3", job_id: "job-001", stage_name: "parse", status: "completed", started_at: "2026-06-01T08:00:31Z", finished_at: "2026-06-01T08:01:45Z", failure_reason: null, detail: { parse_mode: "standard", page_count: 42 }, created_at: "2026-06-01T08:00:31Z", updated_at: "2026-06-01T08:01:45Z" },
    { id: "stg-001-4", job_id: "job-001", stage_name: "normalize", status: "completed", started_at: "2026-06-01T08:01:46Z", finished_at: "2026-06-01T08:02:30Z", failure_reason: null, detail: { normalized_type: "document", block_count: 42 }, created_at: "2026-06-01T08:01:46Z", updated_at: "2026-06-01T08:02:30Z" },
    { id: "stg-001-5", job_id: "job-001", stage_name: "ai_governance", status: "completed", started_at: "2026-06-01T08:02:31Z", finished_at: "2026-06-01T08:03:10Z", failure_reason: null, detail: { classification: "D1", level: "L2", confidence: 0.92 }, created_at: "2026-06-01T08:02:31Z", updated_at: "2026-06-01T08:03:10Z" },
  ],
  "job-003": [
    { id: "stg-003-1", job_id: "job-003", stage_name: "ingest_validate", status: "completed", started_at: "2026-06-01T09:00:01Z", finished_at: "2026-06-01T09:00:20Z", failure_reason: null, detail: { result: "pass" }, created_at: "2026-06-01T09:00:01Z", updated_at: "2026-06-01T09:00:20Z" },
    { id: "stg-003-2", job_id: "job-003", stage_name: "assetize", status: "completed", started_at: "2026-06-01T09:00:21Z", finished_at: "2026-06-01T09:01:00Z", failure_reason: null, detail: { asset_id: "asset-003", version_id: "ver-003" }, created_at: "2026-06-01T09:00:21Z", updated_at: "2026-06-01T09:01:00Z" },
    { id: "stg-003-3", job_id: "job-003", stage_name: "normalize", status: "processing", started_at: "2026-06-01T09:01:01Z", finished_at: null, failure_reason: null, detail: { normalized_type: "record" }, created_at: "2026-06-01T09:01:01Z", updated_at: "2026-06-01T09:15:00Z" },
  ],
};

export const MOCK_JOBS: Job[] = [
  {
    id: "job-001", job_type: "pipeline_a", status: "completed", ingest_batch_id: "batch-001",
    raw_object_id: "raw-001", retry_count: 0, current_stage: "ai_governance",
    failure_reason: null, trace_id: "trace-abc123", metadata_summary: {},
    created_at: "2026-06-01T08:00:00Z", updated_at: "2026-06-01T08:03:15Z",
  },
  {
    id: "job-002", job_type: "pipeline_a", status: "completed", ingest_batch_id: "batch-002",
    raw_object_id: "raw-002", retry_count: 0, current_stage: "ai_governance",
    failure_reason: null, trace_id: "trace-def456", metadata_summary: {},
    created_at: "2026-06-01T08:30:00Z", updated_at: "2026-06-01T08:32:45Z",
  },
  {
    id: "job-003", job_type: "pipeline_b", status: "processing", ingest_batch_id: "batch-003",
    raw_object_id: "raw-003", retry_count: 0, current_stage: "normalize",
    failure_reason: null, trace_id: "trace-ghi789", metadata_summary: {},
    created_at: "2026-06-01T09:00:00Z", updated_at: "2026-06-01T09:15:00Z",
  },
  {
    id: "job-004", job_type: "pipeline_a", status: "completed", ingest_batch_id: "batch-004",
    raw_object_id: "raw-004", retry_count: 1, current_stage: "complete",
    failure_reason: null, trace_id: "trace-jkl012", metadata_summary: {},
    created_at: "2026-05-31T14:00:00Z", updated_at: "2026-05-31T14:03:00Z",
  },
  {
    id: "job-005", job_type: "pipeline_a", status: "failed", ingest_batch_id: "batch-005",
    raw_object_id: null, retry_count: 3, current_stage: "ingest_validate",
    failure_reason: "checksum mismatch: expected sha256:xxx, got sha256:yyy",
    trace_id: "trace-mno345", metadata_summary: {},
    created_at: "2026-05-30T10:00:00Z", updated_at: "2026-05-30T10:05:00Z",
  },
];

// ── Assets ─────────────────────────────────────────────────────

export const MOCK_ASSET_VERSIONS: AssetVersion[] = [
  { id: "ver-001", asset_id: "asset-001", raw_object_id: "raw-001", version_no: 1, version_status: "available", source_checksum: "sha256:a1b2c3...", failure_reason: null, metadata_summary: {}, created_at: "2026-06-01T08:00:30Z", updated_at: "2026-06-01T08:03:15Z" },
  { id: "ver-003", asset_id: "asset-003", raw_object_id: "raw-003", version_no: 1, version_status: "processing", source_checksum: "sha256:c3d4e5...", failure_reason: null, metadata_summary: {}, created_at: "2026-06-01T09:01:00Z", updated_at: "2026-06-01T09:15:00Z" },
  { id: "ver-004", asset_id: "asset-004", raw_object_id: "raw-004", version_no: 1, version_status: "available", source_checksum: "sha256:d4e5f6...", failure_reason: null, metadata_summary: {}, created_at: "2026-05-31T14:00:30Z", updated_at: "2026-05-31T14:03:00Z" },
];

export const MOCK_NORMALIZED_REFS: NormalizedAssetRef[] = [
  { id: "ref-001", version_id: "ver-001", normalized_type: "document", object_uri: "s3://nexus-norm/ref-001.json", schema_version: "v3.1", checksum: "sha256:n1...", status: "available", block_count: 42, record_count: 0, metadata_summary: {}, created_at: "2026-06-01T08:02:30Z", updated_at: "2026-06-01T08:03:10Z" },
  { id: "ref-004", version_id: "ver-004", normalized_type: "document", object_uri: "s3://nexus-norm/ref-004.json", schema_version: "v3.1", checksum: "sha256:n4...", status: "available", block_count: 28, record_count: 0, metadata_summary: {}, created_at: "2026-05-31T14:02:00Z", updated_at: "2026-05-31T14:03:00Z" },
];

export const MOCK_ASSETS: Asset[] = [
  { id: "asset-001", data_source_id: "ds-001", source_object_key: "nas/teaching-resources/math/advanced-math-v3.2.pdf", title: "高等数学教学大纲 v3.2", asset_kind: "document", status: "available", org_scope: ["教务处"], metadata_summary: { author: "数学教研室", pages: 42 }, created_at: "2026-06-01T08:00:30Z", updated_at: "2026-06-01T08:03:15Z" },
  { id: "asset-002", data_source_id: "ds-002", source_object_key: "crawler/gov/zhengce/2026-work-plan.html", title: "教育部2026年工作要点", asset_kind: "document", status: "available", org_scope: ["教务处", "信息中心"], metadata_summary: { source: "gov.cn", sections: 8 }, created_at: "2026-06-01T08:31:00Z", updated_at: "2026-06-01T08:32:45Z" },
  { id: "asset-003", data_source_id: "ds-003", source_object_key: "db/hr/employee-training-2026Q2", title: "员工培训记录 2026Q2", asset_kind: "record", status: "processing", org_scope: ["人事部"], metadata_summary: { records: 1280 }, created_at: "2026-06-01T09:01:00Z", updated_at: "2026-06-01T09:15:00Z" },
  { id: "asset-004", data_source_id: "ds-005", source_object_key: "upload/math/linear-algebra-ch6.pdf", title: "线性代数讲义 第六章", asset_kind: "document", status: "available", org_scope: ["教务处"], metadata_summary: { author: "李四", pages: 28 }, created_at: "2026-05-31T14:00:30Z", updated_at: "2026-05-31T14:03:00Z" },
];

export const MOCK_ASSET_DETAIL: AssetDetail = {
  asset: MOCK_ASSETS[0],
  versions: [MOCK_ASSET_VERSIONS[0]],
  normalized_refs: [MOCK_NORMALIZED_REFS[0]],
  current_version: MOCK_ASSET_VERSIONS[0],
  current_normalized_ref: MOCK_NORMALIZED_REFS[0],
};

// ── AI Governance ──────────────────────────────────────────────

export const MOCK_GOVERNANCE_RUNS: AIGovernanceRun[] = [
  {
    id: "gr-001", normalized_ref_id: "ref-001", profile_id: "prof-default",
    model_alias: "azure/gpt-4o", prompt_version: "v2.3",
    ai_output: {
      classification: "D1", level: "L2",
      tags: ["高等数学", "教学大纲", "本科"],
      org_scope: "教务处",
      confidence: 0.92,
      reasoning: "文档标题明确为高等数学教学大纲，内容涵盖函数、极限、导数、积分等典型高等数学知识点，适用范围为本科层次。来源为教务处官方NAS，可信度高。",
      evidence_refs: [
        { field: "title", value: "高等数学教学大纲 v3.2", confidence: 0.95 },
        { field: "source", value: "教务处 NAS", confidence: 0.88 },
        { field: "content_type", value: "教学文档", confidence: 0.93 },
      ],
    },
    quality_summary: {
      quality_score: 88, quality_level: "pass", confidence: 0.90,
      dimension_scores: { completeness: 92, accuracy: 85, consistency: 88, timeliness: 90 },
      check_items: [
        { check_name: "标题完整性", status: "pass", message: "标题包含学科+文档类型", severity: "info" },
        { check_name: "来源可信度", status: "pass", message: "来源为教务处官方NAS", severity: "info" },
        { check_name: "分类一致性", status: "pass", message: "分类与内容匹配", severity: "info" },
      ],
      blocking_reasons: [],
    },
    validation_status: "schema_valid", adoption_status: "auto_adopted",
    validation_error: null,
    created_at: "2026-06-01T08:02:31Z", updated_at: "2026-06-01T08:03:10Z",
  },
  {
    id: "gr-002", normalized_ref_id: "ref-004", profile_id: "prof-default",
    model_alias: "azure/gpt-4o", prompt_version: "v2.3",
    ai_output: {
      classification: "D1", level: "L2",
      tags: ["线性代数", "讲义", "本科"],
      org_scope: "教务处",
      confidence: 0.85,
      reasoning: "文档为线性代数课程讲义第六章，包含矩阵、特征值等内容。作者为校内教师李四。",
    },
    quality_summary: {
      quality_score: 78, quality_level: "pass", confidence: 0.82,
      dimension_scores: { completeness: 80, accuracy: 75, consistency: 82, timeliness: 70 },
      check_items: [
        { check_name: "标题完整性", status: "pass", message: "标题包含课程名+章节号", severity: "info" },
        { check_name: "时效性", status: "warn", message: "未标注学年学期", severity: "warning" },
        { check_name: "格式规范", status: "pass", message: "PDF格式规范", severity: "info" },
      ],
      blocking_reasons: [],
    },
    validation_status: "schema_valid", adoption_status: "review_required",
    validation_error: null,
    created_at: "2026-05-31T14:02:00Z", updated_at: "2026-05-31T14:03:00Z",
  },
  {
    id: "gr-003", normalized_ref_id: "ref-001", profile_id: "prof-strict",
    model_alias: "azure/gpt-4o-mini", prompt_version: "v1.0",
    ai_output: {
      classification: "D2", level: "L3",
      tags: ["考试", "试卷"],
      confidence: 0.45,
      reasoning: "文档包含大量习题和评分标准，可能是试卷。置信度较低，建议人工审核。",
    },
    quality_summary: {
      quality_score: 55, quality_level: "fail", confidence: 0.45,
      dimension_scores: { completeness: 60, accuracy: 40, consistency: 50, timeliness: 70 },
      check_items: [
        { check_name: "分类准确性", status: "fail", message: "低置信度分类，可能误判", severity: "error" },
        { check_name: "置信度阈值", status: "fail", message: "低于0.6自动采纳阈值", severity: "error" },
      ],
      blocking_reasons: ["置信度低于自动采纳阈值", "分类结果与其他运行不一致"],
    },
    validation_status: "schema_valid", adoption_status: "rejected",
    validation_error: null,
    created_at: "2026-06-01T08:03:20Z", updated_at: "2026-06-01T08:04:00Z",
  },
];

// ── Audit Logs ─────────────────────────────────────────────────

export const MOCK_AUDIT_LOGS: AuditLog[] = [
  {
    id: "audit-001", event_type: "INGEST_BATCH_SUBMITTED", actor_type: "user",
    actor_id: "u-001", target_type: "ingest_batch", target_id: "batch-001",
    trace_id: "trace-abc123", summary: { source: "NAS 同步", file_count: 1 },
    created_at: "2026-06-01T08:00:00Z", updated_at: "2026-06-01T08:00:00Z",
  },
  {
    id: "audit-002", event_type: "GOVERNANCE_ADOPTED", actor_type: "system",
    actor_id: "ai-governance", target_type: "governance_result", target_id: "gr-001",
    trace_id: "trace-abc123", summary: { adoption: "auto_adopted", confidence: 0.92 },
    created_at: "2026-06-01T08:03:10Z", updated_at: "2026-06-01T08:03:10Z",
  },
  {
    id: "audit-003", event_type: "RULES_SAVED", actor_type: "user",
    actor_id: "u-001", target_type: "governance_rules", target_id: "rules-v3",
    trace_id: null, summary: { classifications: 4, levels: 4, tags: 6, dimensions: 4 },
    created_at: "2026-06-01T09:30:00Z", updated_at: "2026-06-01T09:30:00Z",
  },
  {
    id: "audit-004", event_type: "VERSION_STATUS_CHANGED", actor_type: "system",
    actor_id: "worker", target_type: "document_version", target_id: "ver-001",
    trace_id: "trace-abc123", summary: { from: "processing", to: "available" },
    created_at: "2026-06-01T08:03:15Z", updated_at: "2026-06-01T08:03:15Z",
  },
  {
    id: "audit-005", event_type: "PIPELINE_FAILED", actor_type: "system",
    actor_id: "worker", target_type: "job", target_id: "job-005",
    trace_id: "trace-mno345", summary: { reason: "checksum mismatch", retries: 3 },
    created_at: "2026-05-30T10:05:00Z", updated_at: "2026-05-30T10:05:00Z",
  },
];

// ── Workbench Stats ────────────────────────────────────────────

export const MOCK_WORKBENCH = {
  pendingReviewCount: 1,
  myPendingTasks: [
    { id: "t-001", type: "governance_review", title: "线性代数讲义 第六章 — 分类审核", priority: "medium", dueAt: "2026-06-03T18:00:00Z", assetId: "asset-004" },
    { id: "t-002", type: "quality_calibrate", title: "员工培训记录 Q2 — 质量校准", priority: "low", dueAt: "2026-06-05T18:00:00Z", assetId: "asset-003" },
  ],
  recentActivities: [
    { action: "提交了 NAS 同步批次", target: "高等数学教学大纲 v3.2", time: "2026-06-01T08:00:00Z", actor: "张三" },
    { action: "AI 自动采纳了治理结果", target: "高等数学教学大纲 v3.2 (D1/L2)", time: "2026-06-01T08:03:10Z", actor: "系统" },
    { action: "编辑了治理规则", target: "governance_rules.json", time: "2026-06-01T09:30:00Z", actor: "张三" },
    { action: "拒绝了低置信 AI 建议", target: "高等数学教学大纲 v3.2 (D2/L3)", time: "2026-06-01T08:04:00Z", actor: "张三" },
    { action: "上传了本地文件", target: "线性代数讲义 第六章", time: "2026-05-31T14:00:00Z", actor: "张三" },
  ],
};
