/**
 * Route handler: GET /api/normalized-refs/:refId/chunks?page=&pageSize=
 *
 * Server-side proxy to the backend's internal chunk-list endpoint. Used by
 * the asset detail "associated chunks" panel. Authenticated via JWT Bearer
 * from the operator's access cookie — no API caller key needed.
 */
import { NextResponse } from "next/server";
import { internalBackendGet } from "@/lib/searchProxy";
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
  const result = await internalBackendGet<ChunkListResponse["data"]>(
    `/internal/v1/normalized-refs/${encodeURIComponent(refId)}/chunks${query ? `?${query}` : ""}`,
  );
  if (!result.ok) {
    return NextResponse.json(result, { status: result.status });
  }
  return NextResponse.json(result);
}
