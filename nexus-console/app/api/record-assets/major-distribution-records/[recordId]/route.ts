import { NextResponse } from "next/server";

import { forwardedHeadersFrom, pickResponseHeaders, proxy } from "@/lib/api/proxy";
import type { MajorDistributionRecord } from "@/lib/api";

export const dynamic = "force-dynamic";

type RouteContext = {
  params: Promise<{ recordId: string }>;
};

export async function PATCH(request: Request, context: RouteContext): Promise<NextResponse> {
  const { recordId } = await context.params;
  if (!recordId) {
    return NextResponse.json(
      { error: { message: "record_id 不能为空" }, meta: { trace_id: null } },
      { status: 400 },
    );
  }
  const body = await request.json().catch(() => null);
  if (body === null) {
    return NextResponse.json(
      { error: { message: "请求体不是合法 JSON" }, meta: { trace_id: null } },
      { status: 400 },
    );
  }
  const result = await proxy<MajorDistributionRecord>(
    `/internal/v1/record-assets/major-distribution-records/${encodeURIComponent(recordId)}`,
    {
      method: "PATCH",
      body,
      forwardHeaders: forwardedHeadersFrom(request),
    },
  );
  return NextResponse.json(result, {
    status: result.ok ? 200 : result.status,
    headers: pickResponseHeaders(result),
  });
}

export async function DELETE(request: Request, context: RouteContext): Promise<NextResponse> {
  const { recordId } = await context.params;
  if (!recordId) {
    return NextResponse.json(
      { error: { message: "record_id 不能为空" }, meta: { trace_id: null } },
      { status: 400 },
    );
  }
  const result = await proxy<{ id: string; deleted: boolean }>(
    `/internal/v1/record-assets/major-distribution-records/${encodeURIComponent(recordId)}`,
    {
      method: "DELETE",
      forwardHeaders: forwardedHeadersFrom(request),
    },
  );
  return NextResponse.json(result, {
    status: result.ok ? 200 : result.status,
    headers: pickResponseHeaders(result),
  });
}
