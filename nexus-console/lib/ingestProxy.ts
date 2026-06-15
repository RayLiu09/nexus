/**
 * Server-side proxy for /v1/ingest/* endpoints.
 *
 * Forwards the NEXUS access token cookie as a Bearer header so the backend
 * can authenticate the request.
 */
import { apiBaseUrl } from "./api";

export interface IngestProxyError {
  ok: false;
  status: number;
  message: string;
}

export interface IngestProxySuccess<T> {
  ok: true;
  status: number;
  data: T;
  traceId: string | null;
}

export type IngestProxyResult<T> = IngestProxySuccess<T> | IngestProxyError;

interface BackendEnvelope<T> {
  data?: T;
  error?: { message?: string };
  meta?: { trace_id?: string };
}

async function readEnvelope<T>(response: Response): Promise<IngestProxyResult<T>> {
  const text = await response.text();
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
      message: body.error?.message ?? `后端返回 HTTP ${response.status}`,
    };
  }
  return {
    ok: true,
    status: response.status,
    data: body.data as T,
    traceId: body.meta?.trace_id ?? null,
  };
}

/** Read the access token cookie and return an Authorization header value. */
async function getAuthHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = {};
  try {
    const { cookies } = await import("next/headers");
    const store = await cookies();
    const token = store.get("nexus_access_token")?.value;
    if (token) headers["authorization"] = `Bearer ${token}`;
  } catch {
    // Not in a request context.
  }
  return headers;
}

export async function ingestProxyGet<T>(path: string): Promise<IngestProxyResult<T>> {
  try {
    const authHeaders = await getAuthHeaders();
    const response = await fetch(`${apiBaseUrl()}${path}`, {
      method: "GET",
      headers: authHeaders,
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

export async function ingestProxyPost<T>(
  path: string,
  payload: unknown,
  headers: Record<string, string> = {},
): Promise<IngestProxyResult<T>> {
  try {
    const authHeaders = await getAuthHeaders();
    const response = await fetch(`${apiBaseUrl()}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json", ...authHeaders, ...headers },
      body: JSON.stringify(payload),
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
