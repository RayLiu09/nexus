/**
 * GET /api/admin/governance-rules/versions/[versionId]
 *
 * Proxy to GET /internal/v1/admin/governance-rules/versions/{version_id}
 * Returns a specific governance rules version by ID (includes full rules_content).
 */
import { NextResponse } from "next/server";

import { proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ versionId: string }> },
): Promise<NextResponse> {
  const { versionId } = await params;
  const result = await proxy<unknown>(
    `/internal/v1/admin/governance-rules/versions/${versionId}`,
  );
  return NextResponse.json(result, { status: result.ok ? 200 : result.status });
}
