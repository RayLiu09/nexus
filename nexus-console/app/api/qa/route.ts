/**
 * Route handler: GET /api/qa?q=...&kb=...&top_k=...
 *
 * 服务端代理 /v1/qa，避免 caller_key 暴露到浏览器。
 */
import { NextResponse } from "next/server";
import { proxyBackendGet } from "@/lib/searchProxy";

export const dynamic = "force-dynamic";

interface QaResult {
  question: string;
  kb: string | null;
  caller_id: string;
  answer: string;
  sources: Array<Record<string, unknown>>;
}

export async function GET(request: Request): Promise<NextResponse> {
  const url = new URL(request.url);
  const q = url.searchParams.get("q");
  if (!q || q.trim().length === 0) {
    return NextResponse.json(
      { ok: false, status: 400, message: "问题 q 不能为空" },
      { status: 400 },
    );
  }

  const backendParams = new URLSearchParams();
  backendParams.set("q", q);
  const kb = url.searchParams.get("kb");
  if (kb) backendParams.set("kb", kb);
  const topK = url.searchParams.get("top_k");
  if (topK) backendParams.set("top_k", topK);

  const result = await proxyBackendGet<QaResult>(`/v1/qa?${backendParams.toString()}`);
  if (!result.ok) {
    return NextResponse.json(result, { status: result.status });
  }
  return NextResponse.json(result);
}
