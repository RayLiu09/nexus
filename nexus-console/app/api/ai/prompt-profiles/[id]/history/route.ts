import { NextResponse } from "next/server";

import { pickResponseHeaders, proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

interface RouteContext {
  params: Promise<{ id: string }>;
}

export async function GET(request: Request, context: RouteContext): Promise<NextResponse> {
  const { id: profileName } = await context.params;
  if (!profileName) {
    return NextResponse.json(
      { ok: false, status: 400, message: "missing profile name" },
      { status: 400 },
    );
  }
  const search = new URL(request.url).searchParams.toString();
  const result = await proxy<unknown>(
    `/internal/v1/ai/prompt-profiles/${encodeURIComponent(profileName)}/history`,
    { search: search || undefined },
  );
  return NextResponse.json(result, {
    status: result.ok ? 200 : result.status,
    headers: pickResponseHeaders(result),
  });
}
