import { NextResponse } from "next/server";

import { internalBackendGet } from "@/lib/searchProxy";
import type { TalentTrainingPlanGraph } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ planId: string }> },
): Promise<Response> {
  const { planId } = await params;
  const result = await internalBackendGet<TalentTrainingPlanGraph>(
    `/internal/v1/talent-training-plans/${encodeURIComponent(planId)}/course-knowledge-graph`,
  );
  if (!result.ok) {
    return NextResponse.json({ error: { message: result.message }, meta: { trace_id: null } }, { status: result.status });
  }
  return NextResponse.json({ data: result.data, meta: { trace_id: result.traceId } }, { status: result.status });
}
