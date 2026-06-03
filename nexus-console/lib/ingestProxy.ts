/**
 * Server-side proxy for /v1/ingest/* endpoints.
 *
 * Unlike `searchProxy`, ingest endpoints do not require X-API-Key in P0
 * (they are mounted under the open ingest router), so this helper just
 * forwards the call to NEXUS_API_BASE_URL and returns a structured result.
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

export async function ingestProxyGet<T>(path: string): Promise<IngestProxyResult<T>> {
  try {
    const response = await fetch(`${apiBaseUrl()}${path}`, {
      method: "GET",
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
): Promise<IngestProxyResult<T>> {
  try {
    const response = await fetch(`${apiBaseUrl()}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
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
