/**
 * Route handler: GET /api/search?q=...&kb=...&top_k=...&similarity_threshold=...
 *
 * 服务端代理，避免把 caller_key 暴露到浏览器 JS。
 */
import { NextResponse } from "next/server";
import { proxyBackendGet } from "@/lib/searchProxy";

export const dynamic = "force-dynamic";

interface SearchResult {
  query: string;
  kb: string | null;
  results: Array<Record<string, unknown>>;
  count: number;
  caller_id: string;
}

export async function GET(request: Request): Promise<NextResponse> {
  const url = new URL(request.url);
  const q = url.searchParams.get("q");
  if (!q || q.trim().length === 0) {
    return NextResponse.json(
      { ok: false, status: 400, message: "查询关键词 q 不能为空" },
      { status: 400 },
    );
  }

  const backendParams = new URLSearchParams();
  backendParams.set("q", q);
  const kb = url.searchParams.get("kb");
  if (kb) backendParams.set("kb", kb);
  const topK = url.searchParams.get("top_k");
  if (topK) backendParams.set("top_k", topK);
  const threshold = url.searchParams.get("similarity_threshold");
  if (threshold) backendParams.set("similarity_threshold", threshold);

  const result = await proxyBackendGet<SearchResult>(
    `/v1/search?${backendParams.toString()}`,
  );
  if (!result.ok) {
    return NextResponse.json(result, { status: result.status });
  }
  return NextResponse.json(result);
}
