import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { proxy } from "@/lib/api/proxy";
import { ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE, isCookieSecure } from "@/lib/auth/token";

const ACCESS_MAX_AGE = 900;
const REFRESH_MAX_AGE = 604800;

interface RefreshResponse {
  access_token: string;
  refresh_token?: string;
  token_type: "bearer";
}

function shouldClearRefreshFailure(status: number, message: string): boolean {
  return status !== 401 || message.toLowerCase().includes("invalid refresh token");
}

export async function refreshServerTokens(): Promise<{ ok: true; traceId: string | null } | { ok: false; status: number; message: string; clearCookies: boolean }> {
  const store = await cookies();
  const refreshToken = store.get(REFRESH_TOKEN_COOKIE)?.value;

  if (!refreshToken) {
    return { ok: false, status: 401, message: "无有效刷新令牌，请重新登录", clearCookies: true };
  }

  const result = await proxy<RefreshResponse>("/internal/v1/auth/refresh", {
    method: "POST",
    body: { refresh_token: refreshToken },
  });

  if (!result.ok) {
    return {
      ok: false,
      status: result.status,
      message: result.message,
      clearCookies: shouldClearRefreshFailure(result.status, result.message),
    };
  }

  store.set(ACCESS_TOKEN_COOKIE, result.data.access_token, {
    httpOnly: true,
    secure: isCookieSecure(),
    sameSite: "lax",
    path: "/",
    maxAge: ACCESS_MAX_AGE,
  });

  if (result.data.refresh_token) {
    store.set(REFRESH_TOKEN_COOKIE, result.data.refresh_token, {
      httpOnly: true,
      secure: isCookieSecure(),
      sameSite: "lax",
      path: "/",
      maxAge: REFRESH_MAX_AGE,
    });
  }

  return { ok: true, traceId: result.traceId };
}

export function applyRefreshFailureCookies(response: NextResponse, failure: { clearCookies: boolean }) {
  if (failure.clearCookies) {
    response.cookies.set(ACCESS_TOKEN_COOKIE, "", { path: "/", maxAge: 0 });
    response.cookies.set(REFRESH_TOKEN_COOKIE, "", { path: "/", maxAge: 0 });
  }
}
