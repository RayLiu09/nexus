/**
 * B8 (§10 Batch B3b) — proxy for POST /internal/v1/query.
 *
 * Query Router v2 entry point. Accepts `{ query: string }`, forwards
 * to nexus-api's /internal/v1/query, and returns the same envelope so
 * the client's fetcher can unwrap it. All auth (JWT cookie) is
 * handled by the underlying `proxy` helper — the frontend never
 * touches raw tokens.
 */
import { NextResponse } from "next/server";

import { pickResponseHeaders, proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

interface QueryRequestBody {
  query?: unknown;
}

export async function POST(request: Request): Promise<NextResponse> {
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
  if (query.length > 2048) {
    return NextResponse.json(
      { ok: false, status: 400, message: "问题长度不能超过 2048 字符" },
      { status: 400 },
    );
  }

  const result = await proxy<unknown>("/internal/v1/query", {
    method: "POST",
    body: { query },
  });

  return NextResponse.json(result, {
    status: result.ok ? 200 : result.status,
    headers: pickResponseHeaders(result),
  });
}
