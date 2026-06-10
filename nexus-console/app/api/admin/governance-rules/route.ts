/**
 * Route handlers: /api/admin/governance-rules
 *
 * GET  → proxy to GET /internal/v1/admin/governance-rules
 * PUT  → proxy to PUT /internal/v1/admin/governance-rules
 *        支持 ?recompute=true&recompute_scope=...
 *
 * Concurrency is handled server-side via DB row-level locking
 * (GovernanceRulesService); the frontend no longer sends If-Match.
 */
import { NextResponse } from "next/server";

import { proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

export async function GET(): Promise<NextResponse> {
  const result = await proxy<unknown>("/internal/v1/admin/governance-rules");
  return NextResponse.json(result, { status: result.ok ? 200 : result.status });
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
    search: search || undefined,
  });
  return NextResponse.json(result, { status: result.ok ? 200 : result.status });
}
