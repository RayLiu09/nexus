/**
 * Server-side helper for proxying /v1/search and /v1/qa to the backend
 * with the operator's caller key.
 *
 * - 后端 /v1/search 与 /v1/qa 走 require_api_caller，需要 X-API-Key 头。
 * - 控制台不能把 caller_key 暴露在浏览器 JS 中：通过 Next.js route handler 服务端代理，
 *   key 仅从 process.env.NEXUS_DEMO_CALLER_KEY 读取。
 * - 缺少 key 时返回结构化错误，由前端引导运维补齐 env。
 */
import { apiBaseUrl } from "./api";

export interface ProxyError {
  ok: false;
  status: number;
  message: string;
}

export interface ProxySuccess<T> {
  ok: true;
  status: number;
  data: T;
  traceId: string | null;
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
    meta?: { trace_id?: string };
  };

  if (!response.ok) {
    return {
      ok: false,
      status: response.status,
      message: envelope.error?.message ?? `后端返回 HTTP ${response.status}`,
    };
  }

  return {
    ok: true,
    status: response.status,
    data: envelope.data as T,
    traceId: envelope.meta?.trace_id ?? null,
  };
}
