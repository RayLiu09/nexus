import { NextResponse } from "next/server";

import { forwardedHeadersFrom, pickResponseHeaders, proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

interface RouteContext {
  params: Promise<{ id: string }>;
}

export async function POST(request: Request, context: RouteContext): Promise<NextResponse> {
  const { id } = await context.params;
  if (!id) {
    return NextResponse.json(
      { ok: false, status: 400, message: "missing profile id" },
      { status: 400 },
    );
  }
  const result = await proxy<unknown>(
    `/internal/v1/ai/prompt-profiles/${encodeURIComponent(id)}/disable`,
    {
      method: "POST",
      forwardHeaders: forwardedHeadersFrom(request),
    },
  );
  return NextResponse.json(result, {
    status: result.ok ? 200 : result.status,
    headers: pickResponseHeaders(result),
  });
}
