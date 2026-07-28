import { NextResponse } from "next/server";
import { proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<NextResponse> {
  const search = new URL(request.url).searchParams.toString();
  const result = await proxy<unknown>("/internal/v1/governance-traces", {
    search: search || undefined,
  });
  return NextResponse.json(
    result.ok
      ? { data: result.data, meta: { trace_id: result.traceId, total: result.total } }
      : { error: { message: result.message }, detail: result.detail ?? null },
    { status: result.status },
  );
}
