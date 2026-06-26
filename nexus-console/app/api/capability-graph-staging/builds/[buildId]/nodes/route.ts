import { pickSearchParams, proxyInternalList } from "../../../../record-assets/_proxy";
import type { CapabilityGraphStagingNode } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  context: { params: Promise<{ buildId: string }> },
): Promise<Response> {
  const { buildId } = await context.params;
  if (!buildId) {
    return Response.json(
      { error: { message: "build_id 不能为空" }, meta: { trace_id: null } },
      { status: 400 },
    );
  }
  const search = pickSearchParams(request, [
    { from: "node_type" },
    { from: "page" },
    { from: "pageSize" },
    { from: "page_size", to: "pageSize" },
  ]);
  return proxyInternalList<CapabilityGraphStagingNode>(
    `/internal/v1/capability-graph-staging/builds/${encodeURIComponent(buildId)}/nodes`,
    search,
  );
}
