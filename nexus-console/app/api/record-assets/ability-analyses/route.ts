import { pickSearchParams, proxyInternalList } from "../_proxy";
import type { AbilityAnalysis } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const search = pickSearchParams(request, [
    { from: "normalized_ref_id" },
    { from: "profile_id" },
    { from: "major_name" },
    { from: "page" },
    { from: "pageSize" },
    { from: "page_size", to: "pageSize" },
  ]);
  return proxyInternalList<AbilityAnalysis>(
    "/internal/v1/record-assets/ability-analyses",
    search,
  );
}
