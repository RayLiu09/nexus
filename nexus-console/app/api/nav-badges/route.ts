import { NextResponse } from "next/server";
import { proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

export async function GET(): Promise<NextResponse> {
  const reviewsResult = await proxy<{ total?: number }>(
    "/internal/v1/governance-reviews/pending/count",
  );
  const tagReviewPendingCount = reviewsResult.ok
    ? (reviewsResult.data.total ?? 0)
    : 0;

  return NextResponse.json({
    ok: true,
    tagReviewPendingCount,
  });
}
