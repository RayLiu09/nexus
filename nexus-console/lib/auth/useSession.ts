"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Session } from "./session";

export interface UseSessionResult {
  session: Session | null;
  isLoading: boolean;
  /** Trigger login by navigating to /login (clears current session first). */
  login: () => void;
  logout: () => void;
  /** Re-read session via /api/auth/session. Call after token refresh. */
  refresh: () => Promise<void>;
}

async function fetchSession(): Promise<Session | null> {
  try {
    const resp = await fetch("/api/auth/session", { cache: "no-store" });
    if (resp.status === 200) {
      const body = await resp.json();
      return body.data as Session;
    }
    return null;
  } catch {
    return null;
  }
}

async function refreshToken(): Promise<boolean> {
  try {
    const resp = await fetch("/api/auth/refresh", { method: "POST" });
    return resp.ok;
  } catch {
    return false;
  }
}

/**
 * Interval between proactive token refreshes (milliseconds).
 * Access token TTL is 15 min (900 s). Refresh at ~12.5 min to leave
 * a comfortable margin before expiry, accounting for clock skew and
 * network latency.
 */
const REFRESH_INTERVAL_MS = (900 - 120 - 30) * 1000; // 750 s ≈ 12.5 min

/**
 * Client-side session hook.
 *
 * The access token cookie is httpOnly — JS cannot read it directly.
 * Session is fetched via /api/auth/session, which reads the cookie
 * server-side and returns the decoded payload.
 *
 * A proactive refresh timer calls /api/auth/refresh before the token
 * expires, keeping it fresh for both server-rendered pages (which read
 * the cookie via next/headers) and client-side API calls.
 */
export function useSession(): UseSessionResult {
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  const refresh = useCallback(async () => {
    const s = await fetchSession();
    if (mountedRef.current) {
      setSession(s);
      setIsLoading(false);
    }
  }, []);

  // ── Mount / unmount lifecycle ────────────────────────────────────
  useEffect(() => {
    mountedRef.current = true;

    // Fetch session on mount
    refresh();

    // Proactive token refresh — keeps the httpOnly access cookie fresh
    // so server-rendered pages never see an expired token.
    intervalRef.current = setInterval(async () => {
      const ok = await refreshToken();
      if (ok && mountedRef.current) {
        // The refresh route set a new access cookie — re-read session.
        await refresh();
      }
    }, REFRESH_INTERVAL_MS);

    // Pause refresh when the tab is hidden; resume on visibility.
    const handleVisibility = () => {
      if (!mountedRef.current) return;
      if (document.hidden) {
        if (intervalRef.current) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
      } else {
        // Tab visible again — refresh immediately, then resume interval
        refreshToken().then((ok) => { if (ok) refresh(); });
        intervalRef.current = setInterval(async () => {
          const ok = await refreshToken();
          if (ok && mountedRef.current) await refresh();
        }, REFRESH_INTERVAL_MS);
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      mountedRef.current = false;
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [refresh]);

  const login = useCallback(() => {
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
  }, []);

  const logout = useCallback(() => {
    if (typeof window !== "undefined") {
      fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
      setSession(null);
      window.location.href = "/login";
    }
  }, []);

  return { session, isLoading, login, logout, refresh };
}
