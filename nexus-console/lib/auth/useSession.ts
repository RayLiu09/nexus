"use client";

import { useCallback, useEffect, useState } from "react";

import { clearClientSession, getClientSession, setClientSession, type Session } from "./session";

export interface UseSessionResult {
  session: Session | null;
  isLoading: boolean;
  login: (s: Session) => void;
  logout: () => void;
  /** 服务端 prefetch 的 session（避免 hydration 闪烁）。 */
  setInitial: (s: Session | null) => void;
}

/**
 * 客户端 session hook。SSR 阶段返回 isLoading=true 占位，挂载后从
 * cookie/localStorage 读真值。可通过 `setInitial` 提前注入服务端读到的
 * session，避免首次渲染闪烁。
 */
export function useSession(): UseSessionResult {
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time init from localStorage/cookie on mount
    setSession(getClientSession());
    setIsLoading(false);
  }, []);

  const login = useCallback((s: Session) => {
    setClientSession(s);
    setSession(s);
  }, []);

  const logout = useCallback(() => {
    clearClientSession();
    setSession(null);
  }, []);

  const setInitial = useCallback((s: Session | null) => {
    setSession(s);
    setIsLoading(false);
  }, []);

  return { session, isLoading, login, logout, setInitial };
}
