/**
 * Route handler: GET /api/knowledge-chunks/:chunkId/preview
 *
 * Server-side proxy for the backend's internal chunk preview endpoint. Returns
 * chunk metadata plus normalized markdown and locator-derived highlight ranges.
 */
import { NextResponse } from "next/server";
import { internalBackendGet } from "@/lib/searchProxy";
import type { ChunkPreviewResponse } from "@/lib/chunkTypes";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ chunkId: string }> },
): Promise<NextResponse> {
  const { chunkId } = await context.params;
  if (!chunkId) {
    return NextResponse.json(
      { ok: false, status: 400, message: "chunk_id 不能为空" },
      { status: 400 },
    );
  }

  const result = await internalBackendGet<ChunkPreviewResponse>(
    `/internal/v1/knowledge-chunks/${encodeURIComponent(chunkId)}/preview`,
  );
  if (!result.ok) {
    return NextResponse.json(result, { status: result.status });
  }
  return NextResponse.json(result);
}
