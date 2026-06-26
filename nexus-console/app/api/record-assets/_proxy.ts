import { NextResponse } from "next/server";

import { internalBackendGet } from "@/lib/searchProxy";

type SearchParamRule = {
  from: string;
  to?: string;
};

export function pickSearchParams(
  request: Request,
  rules: SearchParamRule[],
): string | undefined {
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

export async function proxyInternalList<T>(
  path: string,
  search?: string,
): Promise<NextResponse> {
  const upstreamPath = search ? path + "?" + search : path;
  const result = await internalBackendGet<T[]>(upstreamPath);
  if (!result.ok) {
    return NextResponse.json(
      { error: { message: result.message }, meta: { trace_id: null } },
      { status: result.status },
    );
  }
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
