/**
 * GET /api/admin/governance-rules/versions
 *
 * Proxy to GET /internal/v1/admin/governance-rules/versions
 * Returns version history for governance rules (all versions, newest first).
 */
import { NextResponse } from "next/server";

import { proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

export async function GET(): Promise<NextResponse> {
  const result = await proxy<unknown>(
    "/internal/v1/admin/governance-rules/versions",
  );
  return NextResponse.json(result, { status: result.ok ? 200 : result.status });
}
