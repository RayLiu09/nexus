/**
 * Route handler: /api/ai/prompt-profiles/:id
 *
 * GET → single prompt profile by id
 * Note: 后端目前用 PUT /ai/prompt-profiles/{profile_name}/active 做更新（按 name），
 * 用 POST /ai/prompt-profiles/{id}/disable 做禁用；不在此处直接 PUT。
 */
import { NextResponse } from "next/server";

import { forwardedHeadersFrom, pickResponseHeaders, proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

interface RouteContext {
  params: Promise<{ id: string }>;
}

export async function GET(_request: Request, context: RouteContext): Promise<NextResponse> {
  const { id } = await context.params;
  if (!id) {
    return NextResponse.json(
      { ok: false, status: 400, message: "missing profile id" },
      { status: 400 },
    );
  }
  const result = await proxy<unknown>(`/internal/v1/ai/prompt-profiles/${encodeURIComponent(id)}`);
  return NextResponse.json(result, {
    status: result.ok ? 200 : result.status,
    headers: pickResponseHeaders(result),
  });
}

/**
 * 透传 PUT —— 当前后端**不支持** PUT by id（更新走
 * `PUT /v1/ai/prompt-profiles/{profile_name}/active`）。这里保留以维持
 * 前端调用链路一致，调用方应改走 `/active` 子路由。Track 4 会重写。
 */
export async function PUT(request: Request, context: RouteContext): Promise<NextResponse> {
  const { id } = await context.params;
  if (!id) {
    return NextResponse.json(
      { ok: false, status: 400, message: "missing profile id" },
      { status: 400 },
    );
  }
  const body = await request.json().catch(() => null);
  if (body === null) {
    return NextResponse.json(
      { ok: false, status: 400, message: "请求体不是合法 JSON" },
      { status: 400 },
    );
  }
  const result = await proxy<unknown>(`/internal/v1/ai/prompt-profiles/${encodeURIComponent(id)}`, {
    method: "PUT",
    body,
    forwardHeaders: forwardedHeadersFrom(request),
  });
  return NextResponse.json(result, {
    status: result.ok ? 200 : result.status,
    headers: pickResponseHeaders(result),
  });
}
