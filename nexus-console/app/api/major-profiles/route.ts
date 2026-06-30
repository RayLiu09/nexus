import { pickSearchParams, proxyInternalList } from "../record-assets/_proxy";
import type { MajorProfile } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const search = pickSearchParams(request, [
    { from: "normalized_ref_id" },
    { from: "major_code" },
    { from: "major_name" },
    { from: "occupation" },
    { from: "education_level" },
    { from: "page" },
    { from: "pageSize" },
    { from: "page_size", to: "pageSize" },
  ]);
  return proxyInternalList<MajorProfile>("/internal/v1/major-profiles", search);
}

