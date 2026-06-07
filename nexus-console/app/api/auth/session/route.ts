/**
 * GET /api/auth/session
 *
 * Returns the current session derived from the httpOnly access cookie.
 * Clients can't read the cookie directly anymore — this endpoint exists so
 * pages like `/login` can detect an existing session without re-implementing
 * cookie parsing.
 *
 * - 200 with payload subset if the token decodes and isn't expired
 * - 204 if the cookie is missing or the token is expired
 */
import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { ACCESS_TOKEN_COOKIE } from "@/lib/auth/token";

interface JwtPayload {
  sub: string;
  username?: string;
  display_name?: string;
  role?: string;
  org_id?: string;
  org_name?: string;
  env?: string;
  exp: number;
  iat?: number;
}

function decode(token: string): JwtPayload | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const json = Buffer.from(parts[1], "base64url").toString("utf8");
    const obj = JSON.parse(json) as JwtPayload;
    if (typeof obj.exp !== "number" || typeof obj.sub !== "string") return null;
    return obj;
  } catch {
    return null;
  }
}

export async function GET() {
  const store = await cookies();
  const token = store.get(ACCESS_TOKEN_COOKIE)?.value;
  if (!token) {
    return new NextResponse(null, { status: 204 });
  }
  const payload = decode(token);
  if (!payload || Date.now() / 1000 >= payload.exp - 30) {
    return new NextResponse(null, { status: 204 });
  }
  return NextResponse.json({
    data: {
      id: payload.sub,
      username: payload.username ?? payload.sub,
      displayName: payload.display_name ?? payload.sub,
      role: payload.role ?? "reader",
      orgUnit: { id: payload.org_id ?? "", name: payload.org_name ?? "" },
      env: payload.env ?? "demo",
    },
  });
}
