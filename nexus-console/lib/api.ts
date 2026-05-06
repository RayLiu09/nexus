export type ApiMeta = {
  trace_id?: string;
  total?: number | null;
};

export type ApiEnvelope<T> = {
  data: T;
  meta?: ApiMeta;
};

export type ApiResult<T> = {
  data: T;
  ok: boolean;
  error: string | null;
  traceId: string | null;
};

export type RuntimeState = {
  api: string;
  database: string;
  workers: string;
  queue: string;
  recent_error: string | null;
};

export type OrgUnit = {
  id: string;
  code: string;
  name: string;
  parent_id: string | null;
  status: string;
  created_at: string;
  updated_at: string;
};

export type UserAccount = {
  id: string;
  username: string;
  display_name: string;
  role: string;
  org_unit_id: string | null;
  email: string | null;
  status: string;
  created_at: string;
  updated_at: string;
};

export type ApiCaller = {
  id: string;
  caller_key: string;
  name: string;
  org_scope: string[];
  permission_scope: string[];
  owner_user_id: string | null;
  status: string;
  created_at: string;
  updated_at: string;
};

export type DataSource = {
  id: string;
  code: string;
  name: string;
  source_type: string;
  status: string;
  owner_user_id: string | null;
  org_scope_hint: string[];
  default_governance_hints: Record<string, unknown>;
  description: string | null;
  created_at: string;
  updated_at: string;
};

export type IngestBatch = {
  id: string;
  data_source_id: string;
  idempotency_key: string;
  source_type: string;
  status: string;
  submitted_by_user_id: string | null;
  summary: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type RawObject = {
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
};

export type Job = {
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
};

export type JobStage = {
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
};

export type ParseArtifact = {
  id: string;
  raw_object_id: string;
  document_version_id: string | null;
  artifact_uri: string;
  parse_mode: string;
  checksum: string;
  status: string;
  error: string | null;
  metadata_summary: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type NormalizedAssetRef = {
  id: string;
  version_id: string;
  normalized_type: string;
  object_uri: string;
  schema_version: string;
  checksum: string;
  status: string;
  block_count: number;
  record_count: number;
  metadata_summary: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type DocumentAsset = {
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
};

export type DocumentVersion = {
  id: string;
  asset_id: string;
  raw_object_id: string;
  version_no: number;
  version_status: string;
  source_checksum: string;
  failure_reason: string | null;
  metadata_summary: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type AssetDetail = {
  asset: DocumentAsset;
  versions: DocumentVersion[];
  normalized_refs: NormalizedAssetRef[];
  current_version: DocumentVersion | null;
  current_normalized_ref: NormalizedAssetRef | null;
};

export type AuditLog = {
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
};

export class NexusApiError extends Error {
  status: number;
  traceId: string | null;

  constructor(message: string, status: number, traceId: string | null) {
    super(message);
    this.status = status;
    this.traceId = traceId;
  }
}

export function apiBaseUrl() {
  return (process.env.NEXUS_API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
}

export async function getApiData<T>(path: string, fallback: T): Promise<ApiResult<T>> {
  try {
    const envelope = await requestApi<T>(path, { method: "GET" });
    return {
      data: envelope.data,
      ok: true,
      error: null,
      traceId: envelope.meta?.trace_id ?? null
    };
  } catch (error) {
    return {
      data: fallback,
      ok: false,
      error: error instanceof Error ? error.message : String(error),
      traceId: error instanceof NexusApiError ? error.traceId : null
    };
  }
}

export async function postApiData<T>(
  path: string,
  payload: Record<string, unknown>
): Promise<ApiEnvelope<T>> {
  return requestApi<T>(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload)
  });
}

async function requestApi<T>(path: string, init: RequestInit): Promise<ApiEnvelope<T>> {
  const response = await fetch(`${apiBaseUrl()}${path}`, {
    ...init,
    cache: "no-store"
  });
  const raw = await response.text();
  const parsed = raw ? JSON.parse(raw) : {};
  const traceId = parsed?.meta?.trace_id ?? null;

  if (!response.ok) {
    const message = parsed?.error?.message ?? `NEXUS API ${response.status}`;
    throw new NexusApiError(message, response.status, traceId);
  }

  return parsed as ApiEnvelope<T>;
}

export function formatDateTime(value: string | null | undefined) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  });
}

export function shortId(value: string | null | undefined) {
  if (!value) {
    return "-";
  }
  return value.length > 12 ? `${value.slice(0, 8)}...${value.slice(-4)}` : value;
}

export function textValue(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (Array.isArray(value)) {
    return value.length ? value.join(", ") : "-";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}
