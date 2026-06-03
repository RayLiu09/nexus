/**
 * POST /api/auth/logout
 *
 * Clears both nexus_access_token and nexus_refresh_token cookies.
 * Optionally proxies to backend /v1/auth/logout to invalidate the refresh token.
 */
import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { proxy } from "@/lib/api/proxy";
import { ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE } from "@/lib/auth/token";

export async function POST() {
  const store = await cookies();
  const refreshToken = store.get(REFRESH_TOKEN_COOKIE)?.value;

  // Fire-and-forget: tell backend to invalidate refresh token
  if (refreshToken) {
    proxy("/v1/auth/logout", {
      method: "POST",
      body: { refresh_token: refreshToken },
    }).catch(() => {
      /* best-effort */
    });
  }

  const response = NextResponse.json({ data: { ok: true } });

  response.cookies.set(ACCESS_TOKEN_COOKIE, "", { path: "/", maxAge: 0 });
  response.cookies.set(REFRESH_TOKEN_COOKIE, "", { path: "/", maxAge: 0 });

  return response;
}
