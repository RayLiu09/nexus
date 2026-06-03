/**
 * Server-side session reader for RSC and route handlers.
 *
 * Reads the access token cookie, decodes the JWT payload, and returns
 * a Session. Does NOT verify the signature — that's the backend's job.
 */
import { cookies } from "next/headers";

import { ACCESS_TOKEN_COOKIE, decodeJwtPayload, isTokenExpired } from "./token";
import type { Session, SessionRole } from "./session";

function sessionFromPayload(payload: Record<string, unknown>): Session {
  return {
    id: String(payload.sub ?? ""),
    username: String(payload.username ?? payload.sub ?? ""),
    displayName: String(payload.display_name ?? payload.sub ?? ""),
    role: (payload.role as SessionRole) ?? "reader",
    orgUnit: {
      id: String(payload.org_id ?? ""),
      name: String(payload.org_name ?? ""),
    },
    env: (payload.env as Session["env"]) ?? "demo",
    loggedInAt: (Number(payload.iat) || Math.floor(Date.now() / 1000)) * 1000,
  };
}

export async function getServerSession(): Promise<Session | null> {
  try {
    const store = await cookies();
    const token = store.get(ACCESS_TOKEN_COOKIE)?.value;
    if (!token) return null;
    const payload = decodeJwtPayload(token);
    if (!payload || isTokenExpired(payload)) return null;
    return sessionFromPayload(payload as unknown as Record<string, unknown>);
  } catch {
    return null;
  }
}
