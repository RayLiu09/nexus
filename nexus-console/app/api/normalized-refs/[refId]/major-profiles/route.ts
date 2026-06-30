import { NextResponse } from "next/server";

import { internalBackendGet } from "@/lib/searchProxy";
import type { MajorProfile } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ refId: string }> },
): Promise<Response> {
  const { refId } = await params;
  const result = await internalBackendGet<MajorProfile[]>(
    `/internal/v1/normalized-refs/${encodeURIComponent(refId)}/major-profiles`,
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
