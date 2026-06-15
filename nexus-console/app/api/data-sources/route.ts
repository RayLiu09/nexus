/**
 * Route handler: GET /api/data-sources
 *
 * 客户端组件（如 QuickUploadDrawer）需要按需拉取数据源列表，
 * 在浏览器无法直接访问 /internal/v1/* —— 通过本代理转发。
 *
 * 服务端组件应直接使用 lib/api.ts:getApiData，不走本路由。
 */
import { NextResponse } from "next/server";

import { forwardedHeadersFrom, pickResponseHeaders, proxy } from "@/lib/api/proxy";
import type { DataSource } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<NextResponse> {
  const url = new URL(request.url);
  const search = url.searchParams.toString();
  const result = await proxy<DataSource[]>("/internal/v1/data-sources", {
    method: "GET",
    search: search || undefined,
    forwardHeaders: forwardedHeadersFrom(request),
  });
  return NextResponse.json(result, {
    status: result.ok ? 200 : result.status,
    headers: pickResponseHeaders(result),
  });
}
