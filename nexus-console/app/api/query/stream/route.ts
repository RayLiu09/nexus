/**
 * SSE proxy for POST /internal/v1/query/stream.
 *
 * The generic ``proxy()`` helper is JSON-oriented; SSE needs a raw
 * ``fetch`` + streaming ``Response`` passthrough. We inject the same
 * ``Authorization: Bearer <jwt>`` header the JSON proxy does so
 * backend ``require_user`` accepts the call.
 *
 * Failure envelope is JSON for non-200 responses (so client fetch
 * unwrapping is symmetric with the non-stream route); 200 responses
 * stream the upstream body verbatim.
 */
import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { apiBaseUrl } from "@/lib/api";

export const dynamic = "force-dynamic";

interface QueryRequestBody {
  query?: unknown;
}

const MAX_QUERY_LENGTH = 2048;

export async function POST(request: Request): Promise<Response> {
  let payload: QueryRequestBody;
  try {
    payload = (await request.json()) as QueryRequestBody;
  } catch {
    return NextResponse.json(
      { ok: false, status: 400, message: "请求体必须是 JSON" },
      { status: 400 },
    );
  }

  const query = typeof payload.query === "string" ? payload.query.trim() : "";
  if (!query) {
    return NextResponse.json(
      { ok: false, status: 400, message: "问题 query 不能为空" },
      { status: 400 },
    );
  }
  if (query.length > MAX_QUERY_LENGTH) {
    return NextResponse.json(
      { ok: false, status: 400, message: "问题长度不能超过 2048 字符" },
      { status: 400 },
    );
  }

  const headers: Record<string, string> = { "content-type": "application/json" };
  try {
    const store = await cookies();
    const token = store.get("nexus_access_token")?.value;
    if (token) headers["authorization"] = `Bearer ${token}`;
  } catch {
    // Build-time context — backend returns 401 downstream.
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${apiBaseUrl()}/internal/v1/query/stream`, {
      method: "POST",
      headers,
      body: JSON.stringify({ query }),
      cache: "no-store",
    });
  } catch (err) {
    return NextResponse.json(
      {
        ok: false,
        status: 502,
        message: `调用 NEXUS 后端失败：${err instanceof Error ? err.message : String(err)}`,
      },
      { status: 502 },
    );
  }

  if (!upstream.ok || !upstream.body) {
    // Non-200 responses: relay body as JSON error envelope so the
    // client's SSE consumer can distinguish auth / server errors
    // from a legitimate empty stream.
    const text = await upstream.text().catch(() => "");
    return NextResponse.json(
      {
        ok: false,
        status: upstream.status,
        message: text || `HTTP ${upstream.status}`,
      },
      { status: upstream.status },
    );
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "text/event-stream",
      "cache-control": "no-cache, no-transform",
      "x-accel-buffering": "no",
    },
  });
}
