import { NextResponse } from "next/server";

import { forwardedHeadersFrom, pickResponseHeaders, proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

type RouteContext = { params: Promise<{ assetId: string }> };

export async function PATCH(request: Request, context: RouteContext): Promise<NextResponse> {
  const { assetId } = await context.params;
  if (!assetId) {
    return NextResponse.json({ error: { message: "asset_id 不能为空" } }, { status: 400 });
  }
  const body = await request.json().catch(() => null);
  if (body === null) {
    return NextResponse.json({ error: { message: "请求体不是合法 JSON" } }, { status: 400 });
  }
  const result = await proxy<Record<string, unknown>>(
    `/internal/v1/talent-demand-reports/${encodeURIComponent(assetId)}/identity`,
    { method: "PATCH", body, forwardHeaders: forwardedHeadersFrom(request) },
  );
  return NextResponse.json(result, {
    status: result.ok ? 200 : result.status,
    headers: pickResponseHeaders(result),
  });
}
