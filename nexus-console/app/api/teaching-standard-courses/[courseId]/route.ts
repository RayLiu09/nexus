import { NextResponse } from "next/server";

import { forwardedHeadersFrom, pickResponseHeaders, proxy } from "@/lib/api/proxy";
import type { TeachingStandardCourse } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function PATCH(
  request: Request,
  context: { params: Promise<{ courseId: string }> },
): Promise<NextResponse> {
  const { courseId } = await context.params;
  const body = await request.json().catch(() => null);
  if (body === null) {
    return NextResponse.json(
      { error: { message: "请求体不是合法 JSON" }, meta: { trace_id: null } },
      { status: 400 },
    );
  }
  const result = await proxy<TeachingStandardCourse>(
    `/internal/v1/teaching-standard-courses/${encodeURIComponent(courseId)}`,
    {
      method: "PATCH",
      body,
      forwardHeaders: forwardedHeadersFrom(request),
    },
  );
  return NextResponse.json(
    result.ok
      ? { data: result.data, meta: { trace_id: result.traceId } }
      : { error: { message: result.message }, detail: result.detail ?? null },
    { status: result.status, headers: pickResponseHeaders(result) },
  );
}
