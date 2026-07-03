"use client";

import { useEffect, useState } from "react";

/** Format elapsed milliseconds as a compact string (e.g. "1h 23m 05s"). */
function formatElapsed(ms: number): string {
  if (ms <= 0) return "0s";
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, "0")}m ${String(seconds).padStart(2, "0")}s`;
  if (minutes > 0) return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
  return `${seconds}s`;
}

interface UseElapsedOptions {
  /** ISO-8601 start timestamp. */
  startedAt: string | null;
  /** ISO-8601 finish timestamp. When set, the counter freezes at final duration. */
  finishedAt?: string | null;
}

interface UseElapsedResult {
  /** Human-readable elapsed duration. */
  elapsed: string;
  /** Raw elapsed milliseconds. */
  elapsedMs: number;
  /** Whether the timer is still running (no finishedAt). */
  isRunning: boolean;
}

/**
 * Live elapsed-time counter for job stages, ingest batches, etc.
 * Updates every second while `isRunning` is true; freezes when `finishedAt`
 * is provided or `startedAt` is null.
 */
export function useElapsed({ startedAt, finishedAt }: UseElapsedOptions): UseElapsedResult {
  const startMs = startedAt ? new Date(startedAt).getTime() : null;
  const endMs = finishedAt ? new Date(finishedAt).getTime() : null;
  const isRunning = startMs != null && endMs == null;
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!isRunning) return undefined;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [isRunning, startedAt]);

  if (!startMs) return { elapsed: "-", elapsedMs: 0, isRunning: false };

  const finalMs = endMs ?? now;
  const elapsedMs = Math.max(0, finalMs - startMs);

  return { elapsed: formatElapsed(elapsedMs), elapsedMs, isRunning };
}
