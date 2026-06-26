import { pickSearchParams, proxyInternalList } from "../../../_proxy";
import type { JobDemandRecord } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  context: { params: Promise<{ datasetId: string }> },
): Promise<Response> {
  const { datasetId } = await context.params;
  if (!datasetId) {
    return Response.json(
      { error: { message: "dataset_id 不能为空" }, meta: { trace_id: null } },
      { status: 400 },
    );
  }
  const search = pickSearchParams(request, [
    { from: "city" },
    { from: "industry" },
    { from: "industry_name", to: "industry" },
    { from: "enterprise_size" },
    { from: "employment_type" },
    { from: "page" },
    { from: "pageSize" },
    { from: "page_size", to: "pageSize" },
  ]);
  return proxyInternalList<JobDemandRecord>(
    `/internal/v1/record-assets/job-demand-datasets/${encodeURIComponent(datasetId)}/records`,
    search,
  );
}
