import { NextResponse } from "next/server";

import { pickResponseHeaders, proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

interface KnowledgeRetrievalPlanRequest {
  query?: unknown;
}

export async function POST(request: Request): Promise<NextResponse> {
  let payload: KnowledgeRetrievalPlanRequest;
  try {
    payload = (await request.json()) as KnowledgeRetrievalPlanRequest;
  } catch {
    return NextResponse.json(
      { ok: false, status: 400, message: "请求体必须是 JSON" },
      { status: 400 },
    );
  }

  const query = typeof payload.query === "string" ? payload.query.trim() : "";
  if (!query) {
    return NextResponse.json(
      { ok: false, status: 400, message: "问题 query 不能为空" },
      { status: 400 },
    );
  }

  const result = await proxy<unknown>("/internal/v1/knowledge-retrieval/plans", {
    method: "POST",
    body: { query },
  });

  return NextResponse.json(result, {
    status: result.ok ? 200 : result.status,
    headers: pickResponseHeaders(result),
  });
}
