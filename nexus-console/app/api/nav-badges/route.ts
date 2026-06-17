import { NextResponse } from "next/server";
import { proxy } from "@/lib/api/proxy";
import type { GovernanceRunLike } from "@/lib/governance-runs";
import { selectCurrentReviewRuns } from "@/lib/governance-runs";
import { extractGovernanceTags } from "@/lib/governance-tags";

export const dynamic = "force-dynamic";

interface GovernanceRun extends GovernanceRunLike {
  ai_output: Record<string, unknown> | null;
}

function countTagReviewDrafts(runs: GovernanceRun[]): number {
  let count = 0;
  for (const run of runs) {
    const tags = extractGovernanceTags(run.ai_output);
    if (tags.length === 0) continue;
    const confidence =
      (run.ai_output?.confidence as number) ??
      (run.quality_summary?.confidence as number) ??
      0;
    if (confidence < 0.85) count++;
  }
  return count;
}

export async function GET(): Promise<NextResponse> {
  const result = await proxy<GovernanceRun[]>(
    "/internal/v1/ai/governance-runs",
  );

  if (!result.ok) {
    // Return zero counts on backend failure — badge is best-effort
    return NextResponse.json(
      { ok: true, governancePendingCount: 0, tagReviewPendingCount: 0 },
      { status: 200 },
    );
  }

  const runs = result.data ?? [];
  const governancePendingCount = selectCurrentReviewRuns(runs).length;
  const tagReviewPendingCount = countTagReviewDrafts(runs);

  return NextResponse.json({
    ok: true,
    governancePendingCount,
    tagReviewPendingCount,
  });
}
