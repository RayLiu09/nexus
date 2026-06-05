/**
 * Route handler: GET /api/ingest/batches/:id
 *
 * Used by the client-side batch upload page to poll batch status without
 * exposing NEXUS_API_BASE_URL or auth state to the browser.
 */
import { NextResponse } from "next/server";

import { ingestProxyGet } from "@/lib/ingestProxy";

export const dynamic = "force-dynamic";

interface BatchDetail {
  id: string;
  status: string;
  batch_status_detail: Record<string, string>;
  summary: Record<string, unknown>;
  updated_at: string;
}

interface RouteContext {
  params: Promise<{ id: string }>;
}

export async function GET(_request: Request, context: RouteContext): Promise<NextResponse> {
  const { id } = await context.params;
  if (!id) {
    return NextResponse.json(
      { ok: false, status: 400, message: "missing batch id" },
      { status: 400 },
    );
  }
  const result = await ingestProxyGet<BatchDetail>(`/internal/v1/ingest/batches/${encodeURIComponent(id)}`);
  return NextResponse.json(result, { status: result.ok ? 200 : result.status });
}
