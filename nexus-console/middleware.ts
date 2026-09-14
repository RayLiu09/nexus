/**
 * Route guard middleware.
 *
 * Page routes: missing both nexus_access_token and nexus_refresh_token → redirect to /login.
 * API routes (/api/*): let through — each route handler manages its own
 *   auth via internalBackendGet / getApiData. Redirecting to /login breaks
 *   JSON-based error handling on the client (fetch follows the redirect
 *   and receives HTML instead of a structured 401 envelope).
 *
 * Role enforcement: the two console roles have DISJOINT feature sets
 * (see navigation.ts). We enforce the same allowlist server-side so a
 * business_expert cannot reach `/data-sources` (or vice versa) via a
 * direct URL — they get 302'd to their role home.
 *
 * Excluded paths (no cookie check):
 * - /login (auth page)
 * - /api/auth/* (login/refresh/logout handlers)
 * - /_next/* (static assets)
 * - /images/* (public image assets used by the login page)
 * - /avatars/* (public role avatars)
 * - /favicon.ico, etc.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { CONSOLE_ROLE_HOME, isConsoleSessionRole, type SessionRole } from "@/lib/auth/roles";
import { ADMIN_ONLY_PREFIXES, EXPERT_ONLY_PREFIXES } from "@/lib/navigation";

const PUBLIC_PATHS = ["/login", "/api/", "/_next/", "/images/", "/avatars/", "/favicon.ico"];

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

function matchesPrefix(pathname: string, prefixes: readonly string[]): boolean {
  return prefixes.some((p) => pathname === p || pathname.startsWith(p + "/"));
}

function roleAllowedOnPath(role: SessionRole, pathname: string): boolean {
  if (role === "platform_data_admin") return !matchesPrefix(pathname, EXPERT_ONLY_PREFIXES);
  if (role === "business_expert") return !matchesPrefix(pathname, ADMIN_ONLY_PREFIXES);
  return true;
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

  const role = tokenRole(accessToken);
  if (!isConsoleSessionRole(role)) {
    return deniedConsoleSession(request);
  }

  // Root always redirects to the role-appropriate landing page, so
  // business_expert never sees the admin-only /workbench even for a moment.
  if (pathname === "/") {
    return NextResponse.redirect(new URL(CONSOLE_ROLE_HOME[role], request.url));
  }

  if (!roleAllowedOnPath(role, pathname)) {
    return NextResponse.redirect(new URL(CONSOLE_ROLE_HOME[role], request.url));
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
