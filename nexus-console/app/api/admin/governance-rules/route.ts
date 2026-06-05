/**
 * Route handlers: /api/admin/governance-rules
 *
 * GET  → proxy to GET /v1/admin/governance-rules，透传 ETag
 * PUT  → proxy to PUT /v1/admin/governance-rules，透传 If-Match / Idempotency-Key
 *        支持 ?recompute=true&recompute_scope=... 与上游一致
 */
import { NextResponse } from "next/server";

import {
  forwardedHeadersFrom,
  pickResponseHeaders,
  proxy,
} from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

export async function GET(): Promise<NextResponse> {
  const result = await proxy<unknown>("/internal/v1/admin/governance-rules");
  const init = {
    status: result.ok ? 200 : result.status,
    headers: pickResponseHeaders(result),
  };
  return NextResponse.json(result, init);
}

export async function PUT(request: Request): Promise<NextResponse> {
  const url = new URL(request.url);
  const search = url.searchParams.toString();
  const body = await request.json().catch(() => null);
  if (body === null) {
    return NextResponse.json(
      { ok: false, status: 400, message: "请求体不是合法 JSON" },
      { status: 400 },
    );
  }
  const result = await proxy<unknown>("/internal/v1/admin/governance-rules", {
    method: "PUT",
    body,
    forwardHeaders: forwardedHeadersFrom(request),
    search: search || undefined,
  });
  const init = {
    status: result.ok ? 200 : result.status,
    headers: pickResponseHeaders(result),
  };
  return NextResponse.json(result, init);
}
