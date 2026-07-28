import { NextResponse } from "next/server";
import { proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

export async function GET(): Promise<NextResponse> {
  const reviewsResult = await proxy<unknown[]>("/internal/v1/governance-reviews/pending");
  const tagReviewPendingCount = reviewsResult.ok ? reviewsResult.data.length : 0;

  return NextResponse.json({
    ok: true,
    tagReviewPendingCount,
  });
}
