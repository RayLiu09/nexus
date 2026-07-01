import type { KnowledgeGraphBuild } from "@/lib/api";
import { pickSearchParams, proxyEvidenceGraphList, proxyEvidenceGraphPost } from "../_proxy";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const search = pickSearchParams(request, [
    { from: "normalized_ref_id" },
    { from: "graph_profile" },
    { from: "strategy_version" },
    { from: "status" },
    { from: "page" },
    { from: "pageSize" },
    { from: "page_size", to: "pageSize" },
  ]);
  return proxyEvidenceGraphList<KnowledgeGraphBuild>(
    "/internal/v1/knowledge-graphs/builds",
    search,
  );
}

export async function POST(request: Request): Promise<Response> {
  const payload = (await request.json()) as unknown;
  return proxyEvidenceGraphPost("/internal/v1/knowledge-graphs/builds", payload);
}
