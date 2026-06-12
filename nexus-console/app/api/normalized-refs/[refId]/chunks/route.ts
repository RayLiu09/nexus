/**
 * Route handler: GET /api/normalized-refs/:refId/chunks?page=&pageSize=
 *
 * Server-side proxy to the backend's chunk-list endpoint. Used by the
 * asset detail "associated chunks" panel. Caller key stays server-side.
 */
import { NextResponse } from "next/server";
import { proxyBackendGet } from "@/lib/searchProxy";
import type { ChunkListResponse } from "@/lib/chunkTypes";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  context: { params: Promise<{ refId: string }> },
): Promise<NextResponse> {
  const { refId } = await context.params;
  if (!refId) {
    return NextResponse.json(
      { ok: false, status: 400, message: "ref_id 不能为空" },
      { status: 400 },
    );
  }

  const url = new URL(request.url);
  const backendParams = new URLSearchParams();
  const page = url.searchParams.get("page");
  if (page) backendParams.set("page", page);
  const pageSize = url.searchParams.get("pageSize");
  if (pageSize) backendParams.set("pageSize", pageSize);

  const query = backendParams.toString();
  const result = await proxyBackendGet<ChunkListResponse["data"]>(
    `/open/v1/normalized-refs/${encodeURIComponent(refId)}/chunks${query ? `?${query}` : ""}`,
  );
  if (!result.ok) {
    return NextResponse.json(result, { status: result.status });
  }
  return NextResponse.json(result);
}
