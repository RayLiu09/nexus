import { NextResponse } from "next/server";
import { forwardedHeadersFrom, proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";
export async function POST(request: Request, context: { params: Promise<{ resultId: string }> }): Promise<NextResponse> {
  const { resultId } = await context.params;
  const body = await request.json().catch(() => null);
  if (body === null) return NextResponse.json({ error: { message: "请求体不是合法 JSON" } }, { status: 400 });
  const result = await proxy<unknown>(`/internal/v1/governance-results/${encodeURIComponent(resultId)}/review-decisions`, { method: "POST", body, forwardHeaders: forwardedHeadersFrom(request) });
  return NextResponse.json(result.ok ? { data: result.data, meta: { trace_id: result.traceId } } : { error: { message: result.message }, detail: result.detail ?? null }, { status: result.status });
}
