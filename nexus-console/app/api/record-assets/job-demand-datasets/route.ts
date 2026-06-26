import { pickSearchParams, proxyInternalList } from "../_proxy";
import type { JobDemandDataset } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const search = pickSearchParams(request, [
    { from: "normalized_ref_id" },
    { from: "major" },
    { from: "industry" },
    { from: "industry_name", to: "industry" },
    { from: "page" },
    { from: "pageSize" },
    { from: "page_size", to: "pageSize" },
  ]);
  return proxyInternalList<JobDemandDataset>(
    "/internal/v1/record-assets/job-demand-datasets",
    search,
  );
}
