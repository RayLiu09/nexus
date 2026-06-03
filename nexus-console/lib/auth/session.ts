/**
 * Session type and helpers — JWT-based (Bearer token).
 *
 * Session is derived from the access token's JWT payload.
 * The backend is the authority for token issuance and verification;
 * the frontend only decodes the payload for UI display.
 */

import type { JwtPayload } from "./token";
import { getJwtPayload, clearTokens } from "./token";

// ── Types ─────────────────────────────────────────────────────────────────

export type SessionRole = "platform_admin" | "data_steward" | "reviewer" | "reader";

export interface SessionOrg {
  id: string;
  name: string;
}

export interface Session {
  id: string;
  username: string;
  displayName: string;
  role: SessionRole;
  orgUnit: SessionOrg;
  env: "demo" | "staging" | "prod";
  loggedInAt: number;
}

// ── Cookie constants (for server-side reading) ────────────────────────────

export const SESSION_COOKIE = "nexus_access_token";
export const SESSION_STORAGE_KEY = "nexus.session";

// ── JWT → Session ─────────────────────────────────────────────────────────

function sessionFromPayload(payload: JwtPayload): Session {
  return {
    id: payload.sub,
    username: payload.username ?? payload.sub,
    displayName: payload.display_name ?? payload.sub,
    role: (payload.role as SessionRole) ?? "reader",
    orgUnit: {
      id: payload.org_id ?? "",
      name: payload.org_name ?? "",
    },
    env: (payload.env as Session["env"]) ?? "demo",
    loggedInAt: (payload.iat ?? Math.floor(Date.now() / 1000)) * 1000,
  };
}

// ── Client-side auth helpers ──────────────────────────────────────────────

/** Return current session from JWT access token (client or server). */
export async function getClientSession(): Promise<Session | null> {
  const payload = await getJwtPayload();
  return payload ? sessionFromPayload(payload) : null;
}

/** Synchronous version — client only, from document.cookie. */
export function getClientSessionSync(): Session | null {
  // Dynamic import avoided: inline cookie read + decode for sync client path
  const raw = typeof document !== "undefined"
    ? document.cookie.split(";").find((c) => c.trim().startsWith("nexus_access_token="))
    : undefined;
  if (!raw) return null;
  const token = raw.split("=").slice(1).join("=").trim();
  if (!token) return null;
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    const json = atob(parts[1].replace(/-/g, "+").replace(/_/g, "/"));
    const payload = JSON.parse(json);
    if (typeof payload.exp !== "number" || typeof payload.sub !== "string") return null;
    if (Date.now() / 1000 >= payload.exp - 30) return null;
    return sessionFromPayload(payload);
  } catch {
    return null;
  }
}

/** Logout: clear tokens and redirect to /login. */
export function logout(): void {
  clearTokens();
  if (typeof window !== "undefined") {
    // Also call server endpoint to clear httpOnly refresh cookie
    fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
    window.location.href = "/login";
  }
}

// ── Deprecated mock helpers (kept for backward compat during migration) ───

/** @deprecated Use getClientSession() — JWT based. */
export function encodeSession(s: Session): string {
  return encodeURIComponent(JSON.stringify(s));
}

/** @deprecated Use getClientSession() — JWT based. */
export function decodeSession(raw: string | null | undefined): Session | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(decodeURIComponent(raw));
    if (parsed && typeof parsed.id === "string" && typeof parsed.role === "string") {
      return parsed as Session;
    }
    return null;
  } catch {
    return null;
  }
}

/** @deprecated Use logout() instead. */
export function clearClientSession(): void {
  logout();
}

/** @deprecated Use getClientSessionSync() instead. */
export function setClientSession(_s: Session): void {
  void _s; // no-op in JWT mode — tokens come from backend
}
