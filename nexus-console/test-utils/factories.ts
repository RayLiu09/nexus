// ── DataSource ────────────────────────────────────────────────────────────

export interface DataSourceInput {
  id: string;
  code: string;
  name: string;
  source_type: string;
  status: string;
  owner_user_id: string | null;
  org_scope_hint: string[];
  default_governance_hints: Record<string, unknown>;
  connection_config: Record<string, unknown> | null;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export function makeDataSource(overrides: Partial<DataSourceInput> = {}): DataSourceInput {
  return {
    id: crypto.randomUUID(),
    code: "ds_default",
    name: "Default Data Source",
    source_type: "document",
    status: "active",
    owner_user_id: null,
    org_scope_hint: [],
    default_governance_hints: {},
    connection_config: null,
    description: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

// ── Job ───────────────────────────────────────────────────────────────────

export interface JobInput {
  id: string;
  job_type: string;
  status: string;
  ingest_batch_id: string | null;
  raw_object_id: string | null;
  retry_count: number;
  current_stage: string | null;
  failure_reason: string | null;
  trace_id: string | null;
  metadata_summary: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export function makeJob(overrides: Partial<JobInput> = {}): JobInput {
  return {
    id: crypto.randomUUID(),
    job_type: "pipeline_a",
    status: "running",
    ingest_batch_id: null,
    raw_object_id: null,
    retry_count: 0,
    current_stage: "ingest_validate",
    failure_reason: null,
    trace_id: null,
    metadata_summary: {},
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

// ── JobStage ───────────────────────────────────────────────────────────────

export interface JobStageInput {
  id: string;
  job_id: string;
  stage_name: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  failure_reason: string | null;
  detail: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export function makeJobStage(overrides: Partial<JobStageInput> & { job_id: string; stage_name: string }): JobStageInput {
  return {
    id: crypto.randomUUID(),
    status: "running",
    started_at: new Date().toISOString(),
    finished_at: null,
    failure_reason: null,
    detail: {},
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

// ── IngestBatch ────────────────────────────────────────────────────────────

export interface IngestBatchInput {
  id: string;
  data_source_id: string;
  idempotency_key: string;
  source_type: string;
  status: string;
  submitted_by_user_id: string | null;
  summary: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export function makeIngestBatch(overrides: Partial<IngestBatchInput> & { data_source_id: string }): IngestBatchInput {
  return {
    id: crypto.randomUUID(),
    idempotency_key: "ik-test-001",
    source_type: "document",
    status: "submitted",
    submitted_by_user_id: null,
    summary: {},
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

// ── RawObject ──────────────────────────────────────────────────────────────

export interface RawObjectInput {
  id: string;
  batch_id: string;
  data_source_id: string;
  source_type: string;
  source_uri: string | null;
  object_uri: string;
  checksum: string;
  mime_type: string | null;
  size_bytes: number | null;
  status: string;
  metadata_summary: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export function makeRawObject(overrides: Partial<RawObjectInput> & { batch_id: string; data_source_id: string }): RawObjectInput {
  return {
    id: crypto.randomUUID(),
    source_type: "document",
    source_uri: null,
    object_uri: "minio://bucket/key.pdf",
    checksum: "sha256:abc123",
    mime_type: "application/pdf",
    size_bytes: 1024,
    status: "pending",
    metadata_summary: {},
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

// ── DocumentAsset ──────────────────────────────────────────────────────────

export interface DocumentAssetInput {
  id: string;
  data_source_id: string;
  source_object_key: string;
  title: string;
  asset_kind: string;
  status: string;
  org_scope: string[];
  metadata_summary: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export function makeDocumentAsset(overrides: Partial<DocumentAssetInput> & { data_source_id: string }): DocumentAssetInput {
  return {
    id: crypto.randomUUID(),
    source_object_key: "doc/001",
    title: "Test Document",
    asset_kind: "document",
    status: "available",
    org_scope: ["d1"],
    metadata_summary: {},
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

// ── AuditLog ───────────────────────────────────────────────────────────────

export interface AuditLogInput {
  id: string;
  event_type: string;
  actor_type: string | null;
  actor_id: string | null;
  target_type: string;
  target_id: string;
  trace_id: string | null;
  summary: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export function makeAuditLog(overrides: Partial<AuditLogInput> & { target_id: string }): AuditLogInput {
  return {
    id: crypto.randomUUID(),
    event_type: "JOB_CREATED",
    actor_type: "user",
    actor_id: null,
    target_type: "job",
    trace_id: null,
    summary: {},
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}
