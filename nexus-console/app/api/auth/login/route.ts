/**
 * POST /api/auth/login
 *
 * Proxies username/password to backend /v1/auth/login.
 * On success: sets nexus_access_token cookie (JS-readable) and
 * nexus_refresh_token cookie (httpOnly). Returns session info.
 */
import { NextResponse } from "next/server";

import { proxy } from "@/lib/api/proxy";
import { ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE, isCookieSecure } from "@/lib/auth/token";

// Cookies from backend are short-lived; maxAge values are coordinated with backend.
const ACCESS_MAX_AGE = 900; // 15 min
const REFRESH_MAX_AGE = 604800; // 7 days

interface LoginRequest {
  username: string;
  password: string;
}

interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  user: {
    id: string;
    username: string;
    display_name: string;
    role: string;
    org_id: string;
    org_name: string;
    env?: string;
  };
}

export async function POST(request: Request) {
  let body: LoginRequest;
  try {
    body = (await request.json()) as LoginRequest;
  } catch {
    return NextResponse.json(
      { error: { message: "请求格式错误" } },
      { status: 400 },
    );
  }

  if (!body.username || !body.password) {
    return NextResponse.json(
      { error: { message: "请输入用户名和密码" } },
      { status: 400 },
    );
  }

  const result = await proxy<LoginResponse>("/internal/v1/auth/login", {
    method: "POST",
    body: { username: body.username, password: body.password },
  });

  if (!result.ok) {
    return NextResponse.json(
      { error: { message: result.message, detail: result.detail } },
      { status: result.status },
    );
  }

  const { access_token, refresh_token, user } = result.data;

  const response = NextResponse.json({
    data: {
      id: user.id,
      username: user.username,
      displayName: user.display_name,
      role: user.role,
      orgUnit: {
        id: user.org_id,
        name: user.org_name,
      },
      env: user.env ?? "demo",
    },
    meta: { trace_id: result.traceId },
  });

  // Access token is httpOnly so XSS cannot read it. Client requests stay
  // same-origin via /api/* route handlers, which forward Bearer via the
  // server-side cookie read in `lib/api/proxy.ts`.
  response.cookies.set(ACCESS_TOKEN_COOKIE, access_token, {
    httpOnly: true,
    secure: isCookieSecure(),
    sameSite: "lax",
    path: "/",
    maxAge: ACCESS_MAX_AGE,
  });

  // Set refresh token — httpOnly for security
  response.cookies.set(REFRESH_TOKEN_COOKIE, refresh_token, {
    httpOnly: true,
    secure: isCookieSecure(),
    sameSite: "lax",
    path: "/",
    maxAge: REFRESH_MAX_AGE,
  });

  return response;
}
