/**
 * Route guard middleware.
 *
 * Checks for nexus_access_token cookie on protected routes.
 * Missing/expired token → redirect to /login.
 *
 * Excluded paths:
 * - /login (auth page)
 * - /api/auth/* (login/refresh/logout handlers)
 * - /_next/* (static assets)
 * - /favicon.ico, etc.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login", "/api/auth/", "/_next/", "/favicon.ico"];

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

  // Optional: decode JWT and check expiry here.
  // For now, existence check is sufficient; the backend validates on each API call.
  // If the token is expired, the API layer will handle 401 → refresh → retry.

  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Match all paths except:
     * - /login (public)
     * - /api/auth/* (auth handlers)
     * - /_next/* (Next.js internals)
     */
    "/((?!login|api/auth|_next|favicon.ico).*)",
  ],
};
