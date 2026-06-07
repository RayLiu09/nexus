/**
 * Route handler: /api/data-sources/:id
 *
 * 当前仅暴露 PATCH（用于 connector config 保存）。
 * GET/list 由服务端组件直接调 `lib/api.ts:getApiData`，无需走代理。
 */
import { NextResponse } from "next/server";

import { forwardedHeadersFrom, pickResponseHeaders, proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

interface RouteContext {
  params: Promise<{ id: string }>;
}

export async function DELETE(request: Request, context: RouteContext): Promise<NextResponse> {
  const { id } = await context.params;
  if (!id) {
    return NextResponse.json(
      { ok: false, status: 400, message: "missing data source id" },
      { status: 400 },
    );
  }
  const url = new URL(request.url);
  const search = url.searchParams.toString();
  const result = await proxy<unknown>(`/internal/v1/data-sources/${encodeURIComponent(id)}`, {
    method: "DELETE",
    search: search || undefined,
    forwardHeaders: forwardedHeadersFrom(request),
  });
  return NextResponse.json(result, {
    status: result.ok ? 200 : result.status,
    headers: pickResponseHeaders(result),
  });
}


export async function PATCH(request: Request, context: RouteContext): Promise<NextResponse> {
  const { id } = await context.params;
  if (!id) {
    return NextResponse.json(
      { ok: false, status: 400, message: "missing data source id" },
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
  const result = await proxy<unknown>(`/internal/v1/data-sources/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body,
    forwardHeaders: forwardedHeadersFrom(request),
  });
  return NextResponse.json(result, {
    status: result.ok ? 200 : result.status,
    headers: pickResponseHeaders(result),
  });
}
