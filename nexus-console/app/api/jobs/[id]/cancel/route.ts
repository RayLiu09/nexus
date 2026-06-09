import { NextResponse } from "next/server";

import { pickResponseHeaders, proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

type RouteContext = { params: Promise<{ id: string }> };

export async function POST(
  _request: Request,
  context: RouteContext,
): Promise<NextResponse> {
  const { id } = await context.params;
  const result = await proxy<unknown>(`/internal/v1/jobs/${id}/cancel`, {
    method: "POST",
  });
  return NextResponse.json(result, {
    status: result.ok ? 200 : result.status,
    headers: pickResponseHeaders(result),
  });
}
