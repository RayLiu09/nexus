/**
 * POST /api/auth/refresh
 *
 * Reads the httpOnly nexus_refresh_token cookie and proxies to backend
 * /v1/auth/refresh. On success, rotates the access and refresh cookies.
 */
import { NextResponse } from "next/server";

import { applyRefreshFailureCookies, refreshServerTokens } from "@/lib/auth/serverRefresh";

export async function POST() {
  const result = await refreshServerTokens();

  if (!result.ok) {
    const response = NextResponse.json(
      { error: { message: result.message } },
      { status: result.status },
    );
    applyRefreshFailureCookies(response, result);
    return response;
  }

  return NextResponse.json({
    data: { ok: true },
    meta: { trace_id: result.traceId },
  });
}


export async function GET(request: Request) {
  const url = new URL(request.url);
  const redirectTarget = url.searchParams.get("redirect") || "/";
  const result = await refreshServerTokens();

  if (!result.ok) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("redirect", redirectTarget);
    const response = NextResponse.redirect(loginUrl);
    applyRefreshFailureCookies(response, result);
    return response;
  }

  return NextResponse.redirect(new URL(redirectTarget, request.url));
}
