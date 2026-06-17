"use client";

import { useState, useEffect, useRef, useCallback } from "react";

interface NavBadges {
  governancePendingCount: number;
  tagReviewPendingCount: number;
}

const POLL_INTERVAL_MS = 30_000;

export function useNavBadges(): NavBadges {
  const [badges, setBadges] = useState<NavBadges>({
    governancePendingCount: 0,
    tagReviewPendingCount: 0,
  });
  const mountedRef = useRef(true);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchBadges = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const resp = await fetch("/api/nav-badges", {
        signal: controller.signal,
        credentials: "include",
      });
      if (!controller.signal.aborted && resp.ok) {
        const data = (await resp.json()) as NavBadges;
        if (mountedRef.current) setBadges(data);
      }
    } catch {
      // AbortError or network error — silently keep last value
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    fetchBadges();

    const poll = () => {
      if (!mountedRef.current) return;
      fetchBadges().finally(() => {
        if (mountedRef.current) {
          timerRef.current = setTimeout(poll, POLL_INTERVAL_MS);
        }
      });
    };
    timerRef.current = setTimeout(poll, POLL_INTERVAL_MS);

    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
      abortRef.current?.abort();
    };
  }, [fetchBadges]);

  return badges;
}
