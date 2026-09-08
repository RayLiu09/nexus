import { pickSearchParams, proxyInternalList } from "../record-assets/_proxy";
import type { TeachingStandardCourse } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const search = pickSearchParams(request, [
    { from: "library_id" },
    { from: "course_name" },
    { from: "major_code" },
    { from: "major_name" },
    { from: "education_level" },
    { from: "course_type" },
    { from: "page" },
    { from: "pageSize" },
    { from: "page_size", to: "pageSize" },
  ]);
  return proxyInternalList<TeachingStandardCourse>(
    "/internal/v1/teaching-standard-courses",
    search,
  );
}
