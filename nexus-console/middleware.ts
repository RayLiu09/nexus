/**
 * Route guard middleware.
 *
 * Page routes: missing both nexus_access_token and nexus_refresh_token → redirect to /login.
 * API routes (/api/*): let through — each route handler manages its own
 *   auth via internalBackendGet / getApiData. Redirecting to /login breaks
 *   JSON-based error handling on the client (fetch follows the redirect
 *   and receives HTML instead of a structured 401 envelope).
 *
 * Excluded paths (no cookie check):
 * - /login (auth page)
 * - /api/auth/* (login/refresh/logout handlers)
 * - /_next/* (static assets)
 * - /images/* (public image assets used by the login page)
 * - /favicon.ico, etc.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { isConsoleSessionRole } from "@/lib/auth/roles";

const PUBLIC_PATHS = ["/login", "/api/", "/_next/", "/images/", "/favicon.ico"];

function isPublic(pathname: string): boolean {
  return PUBLIC_PATHS.some((p) => pathname.startsWith(p));
}

function tokenRole(token: string): unknown {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    return (JSON.parse(atob(payload)) as { role?: unknown }).role;
  } catch {
    return null;
  }
}

function deniedConsoleSession(request: NextRequest): NextResponse {
  const loginUrl = new URL("/login", request.url);
  loginUrl.searchParams.set("redirect", request.nextUrl.pathname);
  const response = NextResponse.redirect(loginUrl);
  response.cookies.set("nexus_access_token", "", { path: "/", maxAge: 0 });
  response.cookies.set("nexus_refresh_token", "", { path: "/", maxAge: 0 });
  return response;
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (isPublic(pathname)) {
    return NextResponse.next();
  }

  const accessToken = request.cookies.get("nexus_access_token")?.value;
  const refreshToken = request.cookies.get("nexus_refresh_token")?.value;

  if (!accessToken && refreshToken) {
    const refreshUrl = new URL("/api/auth/refresh", request.url);
    refreshUrl.searchParams.set("redirect", `${pathname}${request.nextUrl.search}`);
    return NextResponse.redirect(refreshUrl);
  }

  if (!accessToken) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("redirect", pathname);
    return NextResponse.redirect(loginUrl);
  }

  if (!isConsoleSessionRole(tokenRole(accessToken))) {
    return deniedConsoleSession(request);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Match all paths except:
     * - /login (public)
     * - /api/* (API routes — auth handled by handlers)
     * - /_next/* (Next.js internals)
     * - /images/* (public image assets)
     */
    "/((?!login|api/|_next|images/|favicon.ico).*)",
  ],
};
