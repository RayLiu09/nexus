import { pickSearchParams, proxyInternalList } from "../_proxy";
import type { MajorDistributionDataset } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const search = pickSearchParams(request, [
    { from: "normalized_ref_id" },
    { from: "major_code" },
    { from: "major_name" },
    { from: "education_level" },
    { from: "year" },
    { from: "page" },
    { from: "pageSize" },
    { from: "page_size", to: "pageSize" },
  ]);
  return proxyInternalList<MajorDistributionDataset>(
    "/internal/v1/record-assets/major-distribution-datasets",
    search,
  );
}
