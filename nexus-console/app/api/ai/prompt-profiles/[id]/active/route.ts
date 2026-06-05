/**
 * Route handler: PUT /api/ai/prompt-profiles/:id/active
 *
 * 对接后端 PUT /v1/ai/prompt-profiles/{profile_name}/active。
 * 注意：路径段命名为 `id` 仅是 Next.js 动态段约束（同一目录层级动态段必须同名）；
 * 调用方实际传入的是 `profile_name`。
 */
import { NextResponse } from "next/server";

import { forwardedHeadersFrom, pickResponseHeaders, proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

interface RouteContext {
  params: Promise<{ id: string }>;
}

export async function PUT(request: Request, context: RouteContext): Promise<NextResponse> {
  const { id: profileName } = await context.params;
  if (!profileName) {
    return NextResponse.json(
      { ok: false, status: 400, message: "missing profile name" },
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
  const result = await proxy<unknown>(
    `/internal/v1/ai/prompt-profiles/${encodeURIComponent(profileName)}/active`,
    {
      method: "PUT",
      body,
      forwardHeaders: forwardedHeadersFrom(request),
    },
  );
  return NextResponse.json(result, {
    status: result.ok ? 200 : result.status,
    headers: pickResponseHeaders(result),
  });
}
