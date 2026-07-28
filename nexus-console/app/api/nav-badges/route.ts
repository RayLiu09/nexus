import { NextResponse } from "next/server";
import { proxy } from "@/lib/api/proxy";
import type { GovernanceRunLike } from "@/lib/governance-runs";
import { selectCurrentReviewRuns } from "@/lib/governance-runs";

export const dynamic = "force-dynamic";

export async function GET(): Promise<NextResponse> {
  const [runsResult, reviewsResult] = await Promise.all([
    proxy<GovernanceRunLike[]>("/internal/v1/ai/governance-runs"),
    proxy<unknown[]>("/internal/v1/governance-reviews/pending"),
  ]);

  if (!runsResult.ok) {
    // Return zero counts on backend failure — badge is best-effort
    return NextResponse.json(
      { ok: true, governancePendingCount: 0, tagReviewPendingCount: 0 },
      { status: 200 },
    );
  }

  const runs = runsResult.data ?? [];
  const governancePendingCount = selectCurrentReviewRuns(runs).length;
  const tagReviewPendingCount = reviewsResult.ok ? reviewsResult.data.length : 0;

  return NextResponse.json({
    ok: true,
    governancePendingCount,
    tagReviewPendingCount,
  });
}
