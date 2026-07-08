import { NextResponse } from "next/server";

import { internalBackendGet } from "@/lib/searchProxy";
import type { KnowledgeOutlineTree } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ refId: string }> },
): Promise<Response> {
  const { refId } = await params;
  const result = await internalBackendGet<KnowledgeOutlineTree>(
    `/internal/v1/normalized-refs/${encodeURIComponent(refId)}/knowledge-outline`,
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
