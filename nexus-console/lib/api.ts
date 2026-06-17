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
  total: number | null;
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
  caller_key: string | null;
  caller_key_hash: string | null;
  name: string;
  org_scope: string[];
  permission_scope: string[];
  owner_user_id: string | null;
  expired_at: string | null;
  revoked_at: string | null;
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
  connection_config: Record<string, unknown> | null;
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
  asset_version_id: string | null;
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

export type Asset = {
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

export type AssetVersion = {
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

export type GovernanceResult = {
  id: string;
  normalized_ref_id: string;
  ai_run_id: string | null;
  classification: string | null;
  level: string | null;
  tags: string[];
  org_scope: string | null;
  index_admission: boolean;
  quality_summary: Record<string, unknown> | null;
  decision_trail: Record<string, unknown>[];
  rules_schema_version: string | null;
  rules_content_hash: string | null;
  status: string;
  created_by: string | null;
  trace_id: string | null;
  created_at: string;
  updated_at: string;
};

export type AssetDetail = {
  asset: Asset;
  versions: AssetVersion[];
  normalized_refs: NormalizedAssetRef[];
  current_version: AssetVersion | null;
  current_normalized_ref: NormalizedAssetRef | null;
  latest_version?: AssetVersion | null;
  latest_normalized_ref?: NormalizedAssetRef | null;
  latest_governance_result?: GovernanceResult | null;
};

export type AIGovernanceRun = {
  id: string;
  normalized_ref_id: string;
  profile_id: string | null;
  model_alias: string;
  prompt_version: string;
  ai_output: Record<string, unknown> | null;
  quality_summary: Record<string, unknown> | null;
  validation_status: string;
  adoption_status: string;
  validation_error: string | null;
  created_at: string;
  updated_at: string;
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
  // On the server (RSC, route handlers) we hit the NEXUS backend directly.
  // On the client we MUST stay same-origin: requests go through the Next.js
  // `/api/*` route handlers so the httpOnly access cookie can be read via
  // `next/headers` and converted into a Bearer header — the browser never
  // sees the token.
  if (typeof window !== "undefined") {
    return "";
  }
  return (process.env.NEXUS_API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
}

// ── Token helpers (inline to avoid circular deps) ────────────────────────

async function getAuthHeader(): Promise<string | null> {
  // Server-side only: the access cookie is `httpOnly: true` so the browser
  // cannot read it. Client requests rely on `credentials: "include"` to send
  // the cookie alongside same-origin /api fetches; the route handler turns
  // it into Bearer via `lib/api/proxy.ts`.
  if (typeof window !== "undefined") {
    return null;
  }
  try {
    const { cookies } = await import("next/headers");
    const store = await cookies();
    const token = store.get("nexus_access_token")?.value;
    return token ? `Bearer ${token}` : null;
  } catch {
    // Not in a request context (e.g., build time).
    return null;
  }
}

async function tryRefreshToken(): Promise<boolean> {
  try {
    if (typeof window === "undefined") return false;
    const resp = await fetch("/api/auth/refresh", { method: "POST" });
    return resp.ok;
  } catch {
    return false;
  }
}

// ── Idempotency Key ──────────────────────────────────────────────────────

let _idempotencyCounter = 0;
function generateIdempotencyKey(): string {
  _idempotencyCounter += 1;
  const ts = Date.now().toString(36);
  const rand = Math.random().toString(36).slice(2, 8);
  const seq = _idempotencyCounter.toString(36);
  return `${ts}-${rand}-${seq}`;
}

// ── Timeout ──────────────────────────────────────────────────────────────

const REQUEST_TIMEOUT_MS = 30_000;

function withTimeout(signal?: AbortSignal | null): AbortSignal {
  const timeout = AbortSignal.timeout(REQUEST_TIMEOUT_MS);
  if (signal) {
    return AbortSignal.any([signal, timeout]);
  }
  return timeout;
}

// ── Core request ──────────────────────────────────────────────────────────

export async function getApiData<T>(
  path: string,
  fallback: T,
  searchParams?: Record<string, string>,
): Promise<ApiResult<T>> {
  try {
    const qs = searchParams ? new URLSearchParams(searchParams).toString() : "";
    const fullPath = qs ? `${path}?${qs}` : path;
    const envelope = await requestApi<T>(fullPath, { method: "GET" });
    return {
      data: envelope.data,
      ok: true,
      error: null,
      traceId: envelope.meta?.trace_id ?? null,
      total: envelope.meta?.total ?? null,
    };
  } catch (error) {
    return {
      data: fallback,
      ok: false,
      error: error instanceof Error ? error.message : String(error),
      traceId: error instanceof NexusApiError ? error.traceId : null,
      total: null,
    };
  }
}

export async function postApiData<T>(
  path: string,
  payload: Record<string, unknown>,
  options?: { idempotencyKey?: string },
): Promise<ApiEnvelope<T>> {
  const key = options?.idempotencyKey ?? generateIdempotencyKey();
  return requestApi<T>(path, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "idempotency-key": key,
    },
    body: JSON.stringify(payload),
  });
}

export async function putApiData<T>(
  path: string,
  payload: Record<string, unknown>,
  options?: { etag?: string },
): Promise<ApiEnvelope<T>> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (options?.etag) headers["if-match"] = options.etag;
  return requestApi<T>(path, {
    method: "PUT",
    headers,
    body: JSON.stringify(payload),
  });
}

export async function patchApiData<T>(
  path: string,
  payload: Record<string, unknown>,
): Promise<ApiEnvelope<T>> {
  return requestApi<T>(path, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteApiData<T = void>(path: string): Promise<ApiEnvelope<T>> {
  return requestApi<T>(path, { method: "DELETE" });
}

async function requestApi<T>(path: string, init: RequestInit): Promise<ApiEnvelope<T>> {
  // Client-side requests must never hit `/internal/v1/*` directly — the
  // backend is on a different origin and the access cookie is httpOnly.
  // Use `/api/*` so the Next.js route handler reads the cookie and forwards
  // the request server-side.
  if (typeof window !== "undefined" && path.startsWith("/internal/v1/")) {
    throw new NexusApiError(
      `Direct /internal/v1 call from client is forbidden: ${path} — use the matching /api/* proxy route instead`,
      400,
      null,
    );
  }

  const authHeader = await getAuthHeader();
  const headers: Record<string, string> = {};
  if (init.headers) {
    for (const [k, v] of Object.entries(init.headers)) {
      headers[k.toLowerCase()] = v as string;
    }
  }
  if (authHeader) headers["authorization"] = authHeader;

  let response = await fetch(`${apiBaseUrl()}${path}`, {
    ...init,
    headers,
    signal: withTimeout(init.signal),
    cache: "no-store",
    // On the client, ensure the httpOnly access cookie tags along on
    // same-origin /api fetches. No-op server-side.
    credentials: typeof window !== "undefined" ? "include" : "same-origin",
  });

  // On client-side 401, attempt refresh and retry once. Server-component
  // page refreshes are handled by middleware redirecting through /api/auth/refresh.
  if (response.status === 401 && typeof window !== "undefined") {
    const refreshed = await tryRefreshToken();
    if (refreshed) {
      const retryAuthHeader = await getAuthHeader();
      const retryHeaders = { ...headers };
      if (retryAuthHeader) retryHeaders["authorization"] = retryAuthHeader;
      response = await fetch(`${apiBaseUrl()}${path}`, {
        ...init,
        headers: retryHeaders,
        signal: withTimeout(init.signal),
        cache: "no-store",
        credentials: typeof window !== "undefined" ? "include" : "same-origin",
      });
    }
  }

  const raw = await response.text();
  let parsed: Record<string, unknown>;
  try {
    parsed = raw ? JSON.parse(raw) : {};
  } catch {
    throw new NexusApiError(
      `Invalid JSON response (status ${response.status})`,
      response.status,
      null,
    );
  }
  const meta = (parsed.meta ?? {}) as { trace_id?: string };
  const traceId = meta.trace_id ?? null;

  if (!response.ok) {
    const errBody = (parsed.error ?? {}) as { message?: string };
    const message = errBody.message ?? `NEXUS API ${response.status}`;
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
    hour12: false,
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
