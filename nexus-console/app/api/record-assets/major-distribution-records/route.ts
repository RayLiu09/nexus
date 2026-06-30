import { pickSearchParams, proxyInternalList } from "../_proxy";
import type { MajorDistributionRecord } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const search = pickSearchParams(request, [
    { from: "normalized_ref_id" },
    { from: "year" },
    { from: "major_code" },
    { from: "major_name" },
    { from: "province_name" },
    { from: "education_level" },
    { from: "region_scope" },
    { from: "min_count" },
    { from: "max_count" },
    { from: "page" },
    { from: "pageSize" },
    { from: "page_size", to: "pageSize" },
  ]);
  return proxyInternalList<MajorDistributionRecord>(
    "/internal/v1/record-assets/major-distribution-records",
    search,
  );
}
