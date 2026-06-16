/**
 * Route handler: GET /api/normalized-refs/:refId/governance-result?view=full|operator|public
 *
 * Server-side proxy for the backend internal governance-result endpoint. Client
 * components must use this route instead of calling `/internal/v1/*` directly
 * so the httpOnly JWT cookie can be forwarded as a Bearer token server-side.
 */
import { NextResponse } from "next/server";
import { proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  context: { params: Promise<{ refId: string }> },
): Promise<NextResponse> {
  const { refId } = await context.params;
  if (!refId) {
    return NextResponse.json(
      { error: { message: "ref_id 不能为空" }, meta: { trace_id: null } },
      { status: 400 },
    );
  }

  const url = new URL(request.url);
  const view = url.searchParams.get("view") ?? "full";
  const result = await proxy<unknown>(
    `/internal/v1/normalized-refs/${encodeURIComponent(refId)}/governance-result`,
    { search: new URLSearchParams({ view }).toString() },
  );

  if (!result.ok) {
    return NextResponse.json(
      { error: { message: result.message }, detail: result.detail ?? null, meta: { trace_id: null } },
      { status: result.status },
    );
  }

  return NextResponse.json(
    { data: result.data, meta: { trace_id: result.traceId } },
    { status: result.status },
  );
}
