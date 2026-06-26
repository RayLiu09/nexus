import { proxyInternalList } from "../../../_proxy";
import type { JobDemandRequirementItem } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ recordId: string }> },
): Promise<Response> {
  const { recordId } = await context.params;
  if (!recordId) {
    return Response.json(
      { error: { message: "record_id 不能为空" }, meta: { trace_id: null } },
      { status: 400 },
    );
  }
  return proxyInternalList<JobDemandRequirementItem>(
    `/internal/v1/record-assets/job-demand-records/${encodeURIComponent(recordId)}/requirement-items`,
  );
}
