/**
 * Route handler: GET /api/knowledge-chunks/:chunkId/semantic-context
 *
 * Server-side proxy for the backend's internal console-only semantic context
 * endpoint. This intentionally does not call or expose `/open/v1/search`.
 */
import { NextResponse } from "next/server";
import { internalBackendGet } from "@/lib/searchProxy";
import type { ChunkSemanticContextResponse } from "@/lib/chunkTypes";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  context: { params: Promise<{ chunkId: string }> },
): Promise<NextResponse> {
  const { chunkId } = await context.params;
  if (!chunkId) {
    return NextResponse.json(
      { ok: false, status: 400, message: "chunk_id 不能为空" },
      { status: 400 },
    );
  }

  const url = new URL(request.url);
  const query = url.searchParams.toString();
  const path = `/internal/v1/knowledge-chunks/${encodeURIComponent(
    chunkId,
  )}/semantic-context${query ? `?${query}` : ""}`;
  const result = await internalBackendGet<ChunkSemanticContextResponse>(path);
  if (!result.ok) {
    return NextResponse.json(result, { status: result.status });
  }
  return NextResponse.json(result);
}
