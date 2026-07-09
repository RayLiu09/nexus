import { NextResponse } from "next/server";

import { internalBackendGet } from "@/lib/searchProxy";

export const dynamic = "force-dynamic";

type ReviewListEnvelope = {
  ref_id: string;
  items: unknown[];
  next_cursor: string | null;
};

export async function GET(
  request: Request,
  { params }: { params: Promise<{ refId: string }> },
): Promise<Response> {
  const { refId } = await params;
  const url = new URL(request.url);
  const search = new URLSearchParams();
  for (const key of ["status", "limit", "cursor"]) {
    const value = url.searchParams.get(key);
    if (value) search.set(key, value);
  }
  const q = search.toString();

  const result = await internalBackendGet<ReviewListEnvelope>(
    `/internal/v1/normalized-refs/${encodeURIComponent(refId)}/knowledge-outline-reviews${q ? `?${q}` : ""}`,
  );
  if (!result.ok) {
    return NextResponse.json(
      { error: { message: result.message }, meta: { trace_id: null } },
      { status: result.status },
    );
  }
  return NextResponse.json(
    { data: result.data, meta: { trace_id: result.traceId } },
    { status: result.status },
  );
}
