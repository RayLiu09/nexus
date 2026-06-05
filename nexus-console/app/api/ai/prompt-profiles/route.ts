/**
 * Route handlers: /api/ai/prompt-profiles
 *
 * GET  → list prompt profiles (透传可选 ?profile_name=)
 * POST → create prompt profile
 */
import { NextResponse } from "next/server";

import { forwardedHeadersFrom, pickResponseHeaders, proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<NextResponse> {
  const url = new URL(request.url);
  const search = url.searchParams.toString();
  const result = await proxy<unknown>("/internal/v1/ai/prompt-profiles", {
    method: "GET",
    search: search || undefined,
  });
  return NextResponse.json(result, {
    status: result.ok ? 200 : result.status,
    headers: pickResponseHeaders(result),
  });
}

export async function POST(request: Request): Promise<NextResponse> {
  const body = await request.json().catch(() => null);
  if (body === null) {
    return NextResponse.json(
      { ok: false, status: 400, message: "请求体不是合法 JSON" },
      { status: 400 },
    );
  }
  const result = await proxy<unknown>("/internal/v1/ai/prompt-profiles", {
    method: "POST",
    body,
    forwardHeaders: forwardedHeadersFrom(request),
  });
  return NextResponse.json(result, {
    status: result.ok ? 200 : result.status,
    headers: pickResponseHeaders(result),
  });
}
