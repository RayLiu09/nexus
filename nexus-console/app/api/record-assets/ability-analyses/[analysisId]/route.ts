import { NextResponse } from "next/server";

import { internalBackendGet } from "@/lib/searchProxy";
import type { AbilityAnalysis } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ analysisId: string }> },
): Promise<Response> {
  const { analysisId } = await context.params;
  if (!analysisId) {
    return Response.json(
      { error: { message: "analysis_id 不能为空" }, meta: { trace_id: null } },
      { status: 400 },
    );
  }

  const result = await internalBackendGet<AbilityAnalysis>(
    `/internal/v1/record-assets/ability-analyses/${encodeURIComponent(analysisId)}`,
  );
  if (!result.ok) {
    return NextResponse.json(
      { error: { message: result.message }, meta: { trace_id: null } },
      { status: result.status },
    );
  }
  return NextResponse.json(
    { data: result.data, meta: { trace_id: result.traceId } },
    { status: result.status },
  );
}
