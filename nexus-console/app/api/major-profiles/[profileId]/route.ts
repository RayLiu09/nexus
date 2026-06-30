import { NextResponse } from "next/server";

import { internalBackendGet } from "@/lib/searchProxy";
import type { MajorProfile } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ profileId: string }> },
): Promise<Response> {
  const { profileId } = await params;
  const result = await internalBackendGet<MajorProfile>(
    `/internal/v1/major-profiles/${encodeURIComponent(profileId)}`,
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
