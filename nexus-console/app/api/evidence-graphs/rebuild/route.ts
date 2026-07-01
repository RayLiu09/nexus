import { proxyEvidenceGraphPost } from "../_proxy";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const payload = (await request.json()) as unknown;
  return proxyEvidenceGraphPost("/internal/v1/knowledge-graphs/rebuild", payload);
}
