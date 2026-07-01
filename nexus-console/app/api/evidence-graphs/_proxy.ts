import { NextResponse } from "next/server";

import { proxy, type ProxyError } from "@/lib/api/proxy";
import { internalBackendGet } from "@/lib/searchProxy";

type SearchParamRule = {
  from: string;
  to?: string;
};

export function pickSearchParams(request: Request, rules: SearchParamRule[]): string | undefined {
  const url = new URL(request.url);
  const search = new URLSearchParams();
  for (const rule of rules) {
    const value = url.searchParams.get(rule.from);
    if (value !== null && value !== "") {
      search.set(rule.to ?? rule.from, value);
    }
  }
  const out = search.toString();
  return out || undefined;
}

export async function proxyEvidenceGraphList<T>(
  path: string,
  search?: string,
): Promise<NextResponse> {
  const upstreamPath = search ? `${path}?${search}` : path;
  const result = await internalBackendGet<T[]>(upstreamPath);
  if (!result.ok) return proxyErrorResponse(result);
  return NextResponse.json(
    {
      data: result.data,
      meta: {
        trace_id: result.traceId,
        page: result.listMeta?.page,
        page_size: result.listMeta?.pageSize,
        total: result.listMeta?.total ?? result.data.length,
      },
    },
    { status: result.status },
  );
}

export async function proxyEvidenceGraphGet<T>(
  path: string,
  search?: string,
): Promise<NextResponse> {
  const upstreamPath = search ? `${path}?${search}` : path;
  const result = await internalBackendGet<T>(upstreamPath);
  if (!result.ok) return proxyErrorResponse(result);
  return NextResponse.json(
    {
      data: result.data,
      meta: { trace_id: result.traceId },
    },
    { status: result.status },
  );
}

export async function proxyEvidenceGraphPost<T>(
  path: string,
  payload: unknown,
): Promise<NextResponse> {
  const result = await proxy<T>(path, { method: "POST", body: payload });
  if (!result.ok) return proxyErrorResponse(result);
  return NextResponse.json(
    {
      data: result.data,
      meta: { trace_id: result.traceId },
    },
    { status: result.status },
  );
}

function proxyErrorResponse(result: ProxyError): NextResponse {
  return NextResponse.json(
    { error: { message: result.message }, detail: result.detail ?? null, meta: { trace_id: null } },
    { status: result.status },
  );
}
