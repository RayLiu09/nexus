/**
 * Route handler: GET /api/normalized-refs/:refId/content
 *
 * Server-side proxy for the backend's normalized payload endpoint.
 * Returns body_markdown + blocks (document) or record_body (record) for
 * the asset detail "原文预览" tab. MinIO read happens server-side; the
 * console only forwards.
 */
import { NextResponse } from "next/server";
import { proxyBackendGet } from "@/lib/searchProxy";
import type { NormalizedRefContent } from "@/lib/chunkTypes";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ refId: string }> },
): Promise<NextResponse> {
  const { refId } = await context.params;
  if (!refId) {
    return NextResponse.json(
      { ok: false, status: 400, message: "ref_id 不能为空" },
      { status: 400 },
    );
  }

  const result = await proxyBackendGet<NormalizedRefContent>(
    `/open/v1/normalized-refs/${encodeURIComponent(refId)}/content`,
  );
  if (!result.ok) {
    return NextResponse.json(result, { status: result.status });
  }
  return NextResponse.json(result);
}
