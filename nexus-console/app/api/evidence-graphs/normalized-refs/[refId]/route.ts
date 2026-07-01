import type { KnowledgeGraphLatestSummary } from "@/lib/api";
import { pickSearchParams, proxyEvidenceGraphGet } from "../../_proxy";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  context: { params: Promise<{ refId: string }> },
): Promise<Response> {
  const { refId } = await context.params;
  if (!refId) {
    return Response.json(
      { error: { message: "ref_id 不能为空" }, meta: { trace_id: null } },
      { status: 400 },
    );
  }
  const search = pickSearchParams(request, [
    { from: "graph_profile" },
    { from: "strategy_version" },
  ]);
  return proxyEvidenceGraphGet<KnowledgeGraphLatestSummary>(
    `/internal/v1/normalized-refs/${encodeURIComponent(refId)}/knowledge-graph`,
    search,
  );
}
