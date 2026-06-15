/**
 * Route guard middleware.
 *
 * Page routes: missing nexus_access_token → redirect to /login.
 * API routes (/api/*): let through — each route handler manages its own
 *   auth via internalBackendGet / getApiData. Redirecting to /login breaks
 *   JSON-based error handling on the client (fetch follows the redirect
 *   and receives HTML instead of a structured 401 envelope).
 *
 * Excluded paths (no cookie check):
 * - /login (auth page)
 * - /api/auth/* (login/refresh/logout handlers)
 * - /_next/* (static assets)
 * - /favicon.ico, etc.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login", "/api/", "/_next/", "/favicon.ico"];

function isPublic(pathname: string): boolean {
  return PUBLIC_PATHS.some((p) => pathname.startsWith(p));
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (isPublic(pathname)) {
    return NextResponse.next();
  }

  const accessToken = request.cookies.get("nexus_access_token")?.value;

  if (!accessToken) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("redirect", pathname);
    return NextResponse.redirect(loginUrl);
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
     */
    "/((?!login|api/|_next|favicon.ico).*)",
  ],
};
