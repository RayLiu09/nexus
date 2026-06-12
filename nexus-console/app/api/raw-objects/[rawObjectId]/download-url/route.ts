/**
 * Route handler: GET /api/raw-objects/:rawObjectId/download-url?ttl_seconds=
 *
 * Server-side proxy for the backend's presigned-URL endpoint. MinIO
 * credentials stay inside nexus-app — neither the operator's browser nor
 * the console process holds them. The console only forwards the caller key
 * (NEXUS_DEMO_CALLER_KEY) via the existing proxyBackendGet helper.
 *
 * The returned download_url is itself short-lived (default 15 min, clamped
 * 60s–1h by the backend), so leakage of the URL has a bounded blast radius.
 */
import { NextResponse } from "next/server";
import { proxyBackendGet } from "@/lib/searchProxy";
import type { RawDownloadResponse } from "@/lib/chunkTypes";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  context: { params: Promise<{ rawObjectId: string }> },
): Promise<NextResponse> {
  const { rawObjectId } = await context.params;
  if (!rawObjectId) {
    return NextResponse.json(
      { ok: false, status: 400, message: "raw_object_id 不能为空" },
      { status: 400 },
    );
  }

  const url = new URL(request.url);
  const ttl = url.searchParams.get("ttl_seconds");
  const backendParams = new URLSearchParams();
  if (ttl) backendParams.set("ttl_seconds", ttl);

  const query = backendParams.toString();
  const result = await proxyBackendGet<RawDownloadResponse>(
    `/open/v1/raw-objects/${encodeURIComponent(rawObjectId)}/download-url${
      query ? `?${query}` : ""
    }`,
  );
  if (!result.ok) {
    return NextResponse.json(result, { status: result.status });
  }
  return NextResponse.json(result);
}
