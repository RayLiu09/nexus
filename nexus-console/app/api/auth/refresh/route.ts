/**
 * POST /api/auth/refresh
 *
 * Reads the httpOnly nexus_refresh_token cookie and proxies to backend
 * /v1/auth/refresh. On success, rotates the access token cookie.
 */
import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { proxy } from "@/lib/api/proxy";
import { ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE } from "@/lib/auth/token";

const ACCESS_MAX_AGE = 900;

interface RefreshResponse {
  access_token: string;
  refresh_token?: string;
  token_type: "bearer";
}

export async function POST() {
  const store = await cookies();
  const refreshToken = store.get(REFRESH_TOKEN_COOKIE)?.value;

  if (!refreshToken) {
    return NextResponse.json(
      { error: { message: "无有效刷新令牌，请重新登录" } },
      { status: 401 },
    );
  }

  const result = await proxy<RefreshResponse>("/internal/v1/auth/refresh", {
    method: "POST",
    body: { refresh_token: refreshToken },
  });

  if (!result.ok) {
    // Clear stale cookies on refresh failure
    const response = NextResponse.json(
      { error: { message: result.message } },
      { status: result.status },
    );
    response.cookies.set(ACCESS_TOKEN_COOKIE, "", { path: "/", maxAge: 0 });
    response.cookies.set(REFRESH_TOKEN_COOKIE, "", { path: "/", maxAge: 0 });
    return response;
  }

  const { access_token, refresh_token } = result.data;

  const response = NextResponse.json({
    data: { ok: true },
    meta: { trace_id: result.traceId },
  });

  // httpOnly so XSS cannot exfiltrate the rotated access token.
  response.cookies.set(ACCESS_TOKEN_COOKIE, access_token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: ACCESS_MAX_AGE,
  });

  if (refresh_token) {
    response.cookies.set(REFRESH_TOKEN_COOKIE, refresh_token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: 604800,
    });
  }

  return response;
}
