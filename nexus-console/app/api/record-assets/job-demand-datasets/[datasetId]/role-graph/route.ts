import { NextResponse } from "next/server";

import { internalBackendGet } from "@/lib/searchProxy";
import type { JobDemandRoleGraph } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  context: { params: Promise<{ datasetId: string }> },
): Promise<Response> {
  const { datasetId } = await context.params;
  if (!datasetId) {
    return NextResponse.json(
      { error: { message: "dataset_id 不能为空" }, meta: { trace_id: null } },
      { status: 400 },
    );
  }
  const jobTitle = new URL(request.url).searchParams.get("job_title");
  const search = jobTitle ? `?job_title=${encodeURIComponent(jobTitle)}` : "";
  const result = await internalBackendGet<JobDemandRoleGraph>(
    `/internal/v1/record-assets/job-demand-datasets/${encodeURIComponent(datasetId)}/role-graph${search}`,
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
