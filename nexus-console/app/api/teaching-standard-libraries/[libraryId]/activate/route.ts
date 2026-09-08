import { NextResponse } from "next/server";

import { forwardedHeadersFrom, pickResponseHeaders, proxy } from "@/lib/api/proxy";
import type { TeachingStandardLibrary } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ libraryId: string }> },
): Promise<NextResponse> {
  const { libraryId } = await context.params;
  const result = await proxy<TeachingStandardLibrary & { changed: boolean }>(
    `/internal/v1/teaching-standard-libraries/${encodeURIComponent(libraryId)}/activate`,
    {
      method: "POST",
      body: {},
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
