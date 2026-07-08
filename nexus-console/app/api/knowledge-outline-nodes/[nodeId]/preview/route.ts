import { NextResponse } from "next/server";

import { internalBackendGet } from "@/lib/searchProxy";
import type { KnowledgeOutlineNodePreview } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ nodeId: string }> },
): Promise<Response> {
  const { nodeId } = await params;
  const result = await internalBackendGet<KnowledgeOutlineNodePreview>(
    `/internal/v1/knowledge-outline-nodes/${encodeURIComponent(nodeId)}/preview`,
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
