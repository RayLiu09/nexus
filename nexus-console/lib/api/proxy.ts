/**
 * Generic server-side proxy for `/internal/v1/*` NEXUS API endpoints.
 *
 * Use this in Next.js route handlers (`app/api/.../route.ts`) so the browser
 * never sees `NEXUS_API_BASE_URL`. Mirrors the envelope contract used by
 * `lib/ingestProxy.ts` but adds:
 *  - all HTTP verbs (GET/POST/PUT/PATCH/DELETE)
 *  - `If-Match` / `ETag` round-trip (NX-09 规则配置)
 *  - `Idempotency-Key` passthrough (NX-03/ingest mutations)
 *  - non-JSON / empty body tolerance
 */
import { apiBaseUrl } from "../api";

export interface ProxyError {
  ok: false;
  status: number;
  message: string;
  /** Backend-supplied diagnostic envelope, if parseable. */
  detail?: unknown;
}

export interface ProxySuccess<T> {
  ok: true;
  status: number;
  data: T;
  traceId: string | null;
  /** Response `ETag` header verbatim (used by NX-09 optimistic locking). */
  etag: string | null;
}

export type ProxyResult<T> = ProxySuccess<T> | ProxyError;

export type ProxyMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

interface BackendEnvelope<T> {
  data?: T;
  error?: { message?: string };
  detail?: unknown;
  meta?: { trace_id?: string };
}

export interface ProxyOptions {
  method?: ProxyMethod;
  body?: unknown;
  /** Headers to forward to the upstream NEXUS API. */
  forwardHeaders?: Record<string, string | undefined>;
  /** Optional query string already encoded (without leading `?`). */
  search?: string;
  /**
   * Skip auto-injection of `Authorization: Bearer <nexus_access_token>`.
   * Use when the upstream path is `/open/v1/*` (API-caller-gated) or
   * `/internal/v1/auth/*` (public).
   */
  noAuth?: boolean;
}

const FORWARDED_HEADER_ALLOWLIST: ReadonlyArray<string> = [
  "if-match",
  "if-none-match",
  "idempotency-key",
];

function pickForwardedHeaders(req: Request): Record<string, string> {
  const out: Record<string, string> = {};
  for (const name of FORWARDED_HEADER_ALLOWLIST) {
    const value = req.headers.get(name);
    if (value) out[name] = value;
  }
  return out;
}

/**
 * Pick safe upstream → downstream headers to surface back to the browser
 * (currently only ETag for optimistic locking).
 */
export function pickResponseHeaders(result: ProxyResult<unknown>): Record<string, string> {
  if (!result.ok) return {};
  const headers: Record<string, string> = {};
  if (result.etag) headers.ETag = result.etag;
  if (result.traceId) headers["x-trace-id"] = result.traceId;
  return headers;
}

async function readEnvelope<T>(response: Response): Promise<ProxyResult<T>> {
  const text = await response.text();
  const etag = response.headers.get("ETag");
  let body: BackendEnvelope<T> = {};
  if (text) {
    try {
      body = JSON.parse(text) as BackendEnvelope<T>;
    } catch {
      return {
        ok: false,
        status: response.status,
        message: `后端返回非 JSON 响应：${text.slice(0, 200)}`,
      };
    }
  }
  if (!response.ok) {
    return {
      ok: false,
      status: response.status,
      message:
        body.error?.message ??
        (typeof body.detail === "string" ? body.detail : null) ??
        `后端返回 HTTP ${response.status}`,
      detail: body.detail ?? body.error ?? null,
    };
  }
  return {
    ok: true,
    status: response.status,
    data: body.data as T,
    traceId: body.meta?.trace_id ?? null,
    etag,
  };
}

/**
 * Server-side call to the NEXUS API. Throws only on programmer error —
 * network failures and HTTP errors are folded into `ProxyError`.
 */
export async function proxy<T>(path: string, options: ProxyOptions = {}): Promise<ProxyResult<T>> {
  const { method = "GET", body, forwardHeaders, search, noAuth } = options;
  const url = `${apiBaseUrl()}${path}${search ? `?${search}` : ""}`;
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["content-type"] = "application/json";
  if (!noAuth) {
    // Read the JWT from the request's cookie jar (set by /api/auth/login) and
    // forward it as a Bearer token so backend `require_user` accepts the call.
    try {
      const { cookies } = await import("next/headers");
      const store = await cookies();
      const token = store.get("nexus_access_token")?.value;
      if (token) headers["authorization"] = `Bearer ${token}`;
    } catch {
      // Not in a request context (build-time, etc.) — caller will see a 401.
    }
  }
  if (forwardHeaders) {
    for (const [k, v] of Object.entries(forwardHeaders)) {
      if (v) headers[k] = v;
    }
  }
  try {
    const response = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
    return readEnvelope<T>(response);
  } catch (err) {
    return {
      ok: false,
      status: 502,
      message: `调用 NEXUS 后端失败：${err instanceof Error ? err.message : String(err)}`,
    };
  }
}

/**
 * Convenience: extract allow-listed inbound headers from a route-handler
 * request and merge with explicit overrides.
 */
export function forwardedHeadersFrom(
  request: Request,
  overrides: Record<string, string | undefined> = {},
): Record<string, string | undefined> {
  return { ...pickForwardedHeaders(request), ...overrides };
}
