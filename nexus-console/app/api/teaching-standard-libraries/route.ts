import { pickSearchParams, proxyInternalList } from "../record-assets/_proxy";
import type { TeachingStandardLibrary } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const search = pickSearchParams(request, [
    { from: "major_code" },
    { from: "major_name" },
    { from: "education_level" },
    { from: "status" },
    { from: "page" },
    { from: "pageSize" },
    { from: "page_size", to: "pageSize" },
  ]);
  return proxyInternalList<TeachingStandardLibrary>(
    "/internal/v1/teaching-standard-libraries",
    search,
  );
}
