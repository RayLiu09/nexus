import { pickSearchParams, proxyInternalList } from "../../record-assets/_proxy";
import type { CapabilityGraphStagingBuild } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const search = pickSearchParams(request, [
    { from: "normalized_ref_id" },
    { from: "build_type" },
    { from: "status" },
    { from: "page" },
    { from: "pageSize" },
    { from: "page_size", to: "pageSize" },
  ]);
  return proxyInternalList<CapabilityGraphStagingBuild>(
    "/internal/v1/capability-graph-staging/builds",
    search,
  );
}
