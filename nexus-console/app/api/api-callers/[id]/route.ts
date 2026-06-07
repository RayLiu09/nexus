/**
 * Route handler: /api/api-callers/:id
 *
 * DELETE → soft-revoke an ApiCaller. Idempotent on the backend.
 */
import { NextResponse } from "next/server";

import { forwardedHeadersFrom, pickResponseHeaders, proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

interface RouteContext {
  params: Promise<{ id: string }>;
}

export async function DELETE(request: Request, context: RouteContext): Promise<NextResponse> {
  const { id } = await context.params;
  if (!id) {
    return NextResponse.json(
      { ok: false, status: 400, message: "missing api_caller id" },
      { status: 400 },
    );
  }
  const result = await proxy<unknown>(`/internal/v1/api-callers/${encodeURIComponent(id)}`, {
    method: "DELETE",
    forwardHeaders: forwardedHeadersFrom(request),
  });
  return NextResponse.json(result, {
    status: result.ok ? 200 : result.status,
    headers: pickResponseHeaders(result),
  });
}
