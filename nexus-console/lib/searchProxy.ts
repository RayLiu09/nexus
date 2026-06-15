/**
 * Server-side proxy helpers for backend calls from Next.js route handlers.
 *
 * Two strategies:
 * - proxyBackendGet — open API (/open/v1/*) with X-API-Key from NEXUS_DEMO_CALLER_KEY.
 *   Used by search/QA playgrounds that intentionally exercise the public API.
 * - internalBackendGet — internal API (/internal/v1/*) with JWT Bearer from the
 *   incoming request's nexus_access_token cookie. Used by asset detail chunks,
 *   content preview, and download-url — console-internal features that should
 *   not require an API caller key.
 */
import { apiBaseUrl } from "./api";
import { cookies } from "next/headers";

export interface ProxyError {
  ok: false;
  status: number;
  message: string;
}

export interface ProxyListMeta {
  page?: number;
  pageSize?: number;
  total?: number;
}

export interface ProxySuccess<T> {
  ok: true;
  status: number;
  data: T;
  traceId: string | null;
  /** Populated for list endpoints; absent for scalar responses. */
  listMeta?: ProxyListMeta;
}

export type ProxyResult<T> = ProxySuccess<T> | ProxyError;

function getDemoCallerKey(): string | null {
  const key = process.env.NEXUS_DEMO_CALLER_KEY;
  return key && key.trim().length > 0 ? key : null;
}

/**
 * Proxy a GET call to backend, attaching X-API-Key from env.
 * Throws structured ProxyError instead of swallowing 4xx/5xx.
 */
export async function proxyBackendGet<T>(path: string): Promise<ProxyResult<T>> {
  const key = getDemoCallerKey();
  if (!key) {
    return {
      ok: false,
      status: 503,
      message:
        "NEXUS_DEMO_CALLER_KEY 未配置：检索演示需要在 nexus-console 的环境变量中提供已注册的 api_caller key。",
    };
  }

  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}${path}`, {
      method: "GET",
      headers: { "X-API-Key": key },
      cache: "no-store",
    });
  } catch (err) {
    return {
      ok: false,
      status: 502,
      message: `调用 NEXUS 后端失败：${err instanceof Error ? err.message : String(err)}`,
    };
  }

  let body: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      // 后端通常返回 JSON envelope；解析失败时把原文当作错误消息
      return {
        ok: false,
        status: response.status,
        message: `后端返回非 JSON 响应：${text.slice(0, 200)}`,
      };
    }
  }

  const envelope = (body ?? {}) as {
    data?: T;
    error?: { message?: string };
    meta?: {
      trace_id?: string;
      page?: number;
      page_size?: number;
      total?: number;
    };
  };

  if (!response.ok) {
    return {
      ok: false,
      status: response.status,
      message: envelope.error?.message ?? `后端返回 HTTP ${response.status}`,
    };
  }

  const meta = envelope.meta ?? {};
  const listMeta: ProxyListMeta | undefined =
    meta.page !== undefined || meta.page_size !== undefined || meta.total !== undefined
      ? {
          page: meta.page,
          pageSize: meta.page_size,
          total: meta.total,
        }
      : undefined;

  return {
    ok: true,
    status: response.status,
    data: envelope.data as T,
    traceId: meta.trace_id ?? null,
    listMeta,
  };
}

// ── Internal API proxy (JWT Bearer) ─────────────────────────────────────

async function getInternalAuthHeader(): Promise<string | null> {
  try {
    const store = await cookies();
    const token = store.get("nexus_access_token")?.value;
    return token ? `Bearer ${token}` : null;
  } catch {
    return null;
  }
}

/**
 * Proxy a GET call to the backend's **internal** API (/internal/v1/*) using
 * JWT Bearer auth from the incoming request's httpOnly cookie.
 *
 * Used by console-internal features (asset detail chunks, content preview,
 * download URLs) — these do NOT require an API caller key.
 */
export async function internalBackendGet<T>(path: string): Promise<ProxyResult<T>> {
  // path must start with /internal/v1/
  const authHeader = await getInternalAuthHeader();
  if (!authHeader) {
    return {
      ok: false,
      status: 401,
      message: "未找到有效的访问令牌，请重新登录。",
    };
  }

  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}${path}`, {
      method: "GET",
      headers: { authorization: authHeader },
      cache: "no-store",
    });
  } catch (err) {
    return {
      ok: false,
      status: 502,
      message: `调用 NEXUS 后端失败：${err instanceof Error ? err.message : String(err)}`,
    };
  }

  let body: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      return {
        ok: false,
        status: response.status,
        message: `后端返回非 JSON 响应：${text.slice(0, 200)}`,
      };
    }
  }

  const envelope = (body ?? {}) as {
    data?: T;
    error?: { message?: string };
    meta?: {
      trace_id?: string;
      page?: number;
      page_size?: number;
      total?: number;
    };
  };

  if (!response.ok) {
    return {
      ok: false,
      status: response.status,
      message: envelope.error?.message ?? `后端返回 HTTP ${response.status}`,
    };
  }

  const meta = envelope.meta ?? {};
  const listMeta: ProxyListMeta | undefined =
    meta.page !== undefined || meta.page_size !== undefined || meta.total !== undefined
      ? {
          page: meta.page,
          pageSize: meta.page_size,
          total: meta.total,
        }
      : undefined;

  return {
    ok: true,
    status: response.status,
    data: envelope.data as T,
    traceId: meta.trace_id ?? null,
    listMeta,
  };
}
