import { NextResponse } from "next/server";

import { internalBackendGet } from "@/lib/searchProxy";
import type { KnowledgeOutlineChunkPage } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ nodeId: string }> },
): Promise<Response> {
  const { nodeId } = await params;
  const url = new URL(request.url);
  const search = new URLSearchParams();
  const limit = url.searchParams.get("limit");
  const cursor = url.searchParams.get("cursor");
  if (limit) search.set("limit", limit);
  if (cursor) search.set("cursor", cursor);
  const q = search.toString();

  const result = await internalBackendGet<KnowledgeOutlineChunkPage>(
    `/internal/v1/knowledge-outline-nodes/${encodeURIComponent(nodeId)}/chunks${q ? `?${q}` : ""}`,
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
