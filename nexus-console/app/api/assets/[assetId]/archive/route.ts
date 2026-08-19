import { NextResponse } from "next/server";

import { forwardedHeadersFrom, pickResponseHeaders, proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ assetId: string }> },
): Promise<NextResponse> {
  const { assetId } = await context.params;
  if (!assetId) {
    return NextResponse.json({ ok: false, message: "missing asset id" }, { status: 400 });
  }
  const result = await proxy<unknown>(
    `/internal/v1/assets/${encodeURIComponent(assetId)}/archive`,
    {
      method: "POST",
      body: {},
      forwardHeaders: forwardedHeadersFrom(request),
    },
  );
  return NextResponse.json(result, {
    status: result.ok ? 200 : result.status,
    headers: pickResponseHeaders(result),
  });
}
