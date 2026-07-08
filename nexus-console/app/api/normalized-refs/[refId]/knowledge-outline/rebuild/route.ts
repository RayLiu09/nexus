import { NextResponse } from "next/server";

import { proxy } from "@/lib/api/proxy";
import type { KnowledgeOutlineTree } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ refId: string }> },
): Promise<Response> {
  const { refId } = await params;
  const result = await proxy<KnowledgeOutlineTree>(
    `/internal/v1/normalized-refs/${encodeURIComponent(refId)}/knowledge-outline/rebuild`,
    { method: "POST" },
  );
  if (!result.ok) {
    return NextResponse.json(
      {
        error: { message: result.message },
        detail: result.detail ?? null,
        meta: { trace_id: null },
      },
      { status: result.status },
    );
  }
  return NextResponse.json(
    { data: result.data, meta: { trace_id: result.traceId } },
    { status: result.status },
  );
}
