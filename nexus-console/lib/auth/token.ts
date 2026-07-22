/**
 * Bearer JWT token management — works in both server (RSC/route-handler) and
 * client (browser) environments.
 *
 * Token layout:
 * - nexus_access_token  — httpOnly cookie, short-lived (15 min)
 *   Read by RSC and Next route handlers via `cookies()` for Bearer
 *   attachment. The browser never sees the token in JS — client fetches
 *   stay same-origin via `/api/*` and rely on cookie auto-send.
 * - nexus_refresh_token  — httpOnly cookie, long-lived (7 days)
 *   Only server can read; used by /api/auth/refresh to rotate access tokens.
 *
 * JWT verification is the backend's responsibility. Frontend only decodes
 * the payload (base64url) for UI display and expiry checks.
 */

export interface JwtPayload {
  sub: string; // user_id
  username?: string;
  display_name?: string;
  role?: string;
  org_id?: string;
  org_name?: string;
  env?: string;
  exp: number;
  iat: number;
  jti?: string;
}

const ACCESS_TOKEN_COOKIE = "nexus_access_token";
const REFRESH_TOKEN_COOKIE = "nexus_refresh_token";

function isCookieSecure(): boolean {
  return (
    process.env.NEXUS_COOKIE_SECURE === "true" ||
    (process.env.NEXUS_COOKIE_SECURE !== "false" && process.env.NODE_ENV === "production")
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────

function decodeJwtPayload(token: string): JwtPayload | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    const payload = parts[1];
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    const obj = JSON.parse(json);
    if (typeof obj.exp !== "number" || typeof obj.sub !== "string") return null;
    return obj as JwtPayload;
  } catch {
    return null;
  }
}

function isTokenExpired(payload: JwtPayload, skewSeconds = 30): boolean {
  return Date.now() / 1000 >= payload.exp - skewSeconds;
}

// ── Cookie helpers (isomorphic) ──────────────────────────────────────────

function readCookie(name: string): string | null {
  if (typeof document !== "undefined") {
    const all = document.cookie.split(";");
    for (const part of all) {
      const idx = part.indexOf("=");
      if (idx < 0) continue;
      const key = part.slice(0, idx).trim();
      if (key === name) return part.slice(idx + 1).trim();
    }
    return null;
  }
  return null;
}

function writeCookie(name: string, value: string, maxAgeS: number): void {
  if (typeof document === "undefined") return;
  const parts = [`${name}=${value}`, "path=/", `max-age=${maxAgeS}`, "samesite=lax"];
  if (location.protocol === "https:") parts.push("secure");
  document.cookie = parts.join("; ");
}

function deleteCookie(name: string): void {
  writeCookie(name, "", 0);
}

// ── Public API ───────────────────────────────────────────────────────────

/** Get current access token. Server: reads from cookies(). Client: reads from document.cookie. */
export async function getAccessToken(): Promise<string | null> {
  // Server-side
  if (typeof window === "undefined") {
    try {
      const { cookies } = await import("next/headers");
      const store = await cookies();
      return store.get(ACCESS_TOKEN_COOKIE)?.value ?? null;
    } catch {
      return null;
    }
  }
  // Client-side
  return readCookie(ACCESS_TOKEN_COOKIE);
}

/** Get access token synchronously (client-only, for use in non-async contexts). */
export function getAccessTokenSync(): string | null {
  return readCookie(ACCESS_TOKEN_COOKIE);
}

/** Decode and return the JWT payload from the access token. Returns null if missing or expired. */
export async function getJwtPayload(): Promise<JwtPayload | null> {
  const token = await getAccessToken();
  if (!token) return null;
  const payload = decodeJwtPayload(token);
  if (!payload || isTokenExpired(payload)) return null;
  return payload;
}

/**
 * Set tokens after successful login/refresh.
 * Called from route handlers (server-side) to set httpOnly refresh cookie.
 * Client-side: sets access token cookie.
 */
export function setAccessToken(token: string, maxAgeS = 900): void {
  if (typeof document !== "undefined") {
    writeCookie(ACCESS_TOKEN_COOKIE, token, maxAgeS);
  }
}

/** Clear all auth cookies (client-side helper for logout). */
export function clearTokens(): void {
  deleteCookie(ACCESS_TOKEN_COOKIE);
  // Refresh token is httpOnly — can't clear from client.
  // The /api/auth/logout route handler clears it server-side.
}

/**
 * Build Authorization header value. Works in both environments.
 * Returns null if no token available.
 */
export async function authorizationHeader(): Promise<string | null> {
  const token = await getAccessToken();
  return token ? `Bearer ${token}` : null;
}

export {
  ACCESS_TOKEN_COOKIE,
  REFRESH_TOKEN_COOKIE,
  decodeJwtPayload,
  isCookieSecure,
  isTokenExpired,
};
