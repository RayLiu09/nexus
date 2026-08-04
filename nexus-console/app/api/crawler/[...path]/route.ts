/**
 * Route handler: /api/crawler/*
 *
 * Proxies Console Crawler control-plane calls to /internal/v1/crawler/*.
 */
import { NextResponse } from "next/server";

import { forwardedHeadersFrom, pickResponseHeaders, proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

interface RouteContext {
  params: Promise<{ path: string[] }>;
}

function crawlerPath(parts: string[]): string {
  return `/internal/v1/crawler/${parts.map(encodeURIComponent).join("/")}`;
}

export async function GET(request: Request, context: RouteContext): Promise<NextResponse> {
  const { path } = await context.params;
  const url = new URL(request.url);
  const result = await proxy<unknown>(crawlerPath(path), {
    method: "GET",
    search: url.searchParams.toString() || undefined,
    forwardHeaders: forwardedHeadersFrom(request),
  });
  return NextResponse.json(result, {
    status: result.ok ? 200 : result.status,
    headers: pickResponseHeaders(result),
  });
}

export async function POST(request: Request, context: RouteContext): Promise<NextResponse> {
  const { path } = await context.params;
  const body = await request.json().catch(() => null);
  const result = await proxy<unknown>(crawlerPath(path), {
    method: "POST",
    body: body ?? undefined,
    forwardHeaders: forwardedHeadersFrom(request),
  });
  return NextResponse.json(result, {
    status: result.ok ? 200 : result.status,
    headers: pickResponseHeaders(result),
  });
}
