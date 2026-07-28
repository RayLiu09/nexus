import { NextResponse } from "next/server";
import { proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";
export async function GET(_request: Request, context: { params: Promise<{ resultId: string }> }): Promise<NextResponse> {
  const { resultId } = await context.params;
  const result = await proxy<unknown>(`/internal/v1/governance-results/${encodeURIComponent(resultId)}/review-context`);
  return NextResponse.json(result.ok ? { data: result.data, meta: { trace_id: result.traceId } } : { error: { message: result.message }, detail: result.detail ?? null }, { status: result.status });
}
