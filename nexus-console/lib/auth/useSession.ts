"use client";

import { useCallback, useEffect, useState } from "react";

import { getClientSession, logout as doLogout, type Session } from "./session";

export interface UseSessionResult {
  session: Session | null;
  isLoading: boolean;
  /** Trigger login by navigating to /login (clears current session first). */
  login: () => void;
  logout: () => void;
  /** Re-read session from JWT cookie. Call after token refresh. */
  refresh: () => Promise<void>;
}

/**
 * Client-side session hook. Reads JWT from cookie on mount and exposes
 * session state. login() navigates to /login; logout() clears tokens.
 */
export function useSession(): UseSessionResult {
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    const s = await getClientSession();
    setSession(s);
  }, []);

  useEffect(() => {
    // One-time init from JWT cookie on mount
    getClientSession().then((s) => {
      setSession(s);
      setIsLoading(false);
    });
  }, []);

  const login = useCallback(() => {
    // Clear any stale session and navigate to login
    doLogout();
  }, []);

  const logout = useCallback(() => {
    doLogout();
    setSession(null);
  }, []);

  return { session, isLoading, login, logout, refresh };
}
