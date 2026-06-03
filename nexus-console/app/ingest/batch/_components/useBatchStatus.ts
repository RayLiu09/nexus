"use client";

import { useCallback } from "react";

import { usePolling } from "@/lib/usePolling";

import type { BatchDetail, BatchProxyResult } from "./batch.types";

const POLL_INTERVAL_MS = 5_000;
const TERMINAL_STATUSES = new Set(["completed", "partial_failed", "failed", "duplicate_skipped"]);

interface UseBatchStatusResult {
  detail: BatchDetail | null;
  error: string | null;
  isPolling: boolean;
  isPaused: boolean;
  lastUpdatedAt: number | null;
  lastResponseMs: number | null;
  pause: () => void;
  resume: () => void;
  refresh: () => void;
}

async function fetchBatch(batchId: string, signal: AbortSignal): Promise<BatchDetail> {
  const response = await fetch(`/api/ingest/batches/${encodeURIComponent(batchId)}`, {
    signal,
    cache: "no-store",
  });
  const body = (await response.json()) as BatchProxyResult;
  if (!body.ok) {
    throw new Error(body.message);
  }
  return body.data;
}

export function useBatchStatus(batchId: string | null): UseBatchStatusResult {
  const fn = useCallback(
    (signal: AbortSignal) => {
      if (!batchId) return Promise.resolve(null as unknown as BatchDetail);
      return fetchBatch(batchId, signal);
    },
    [batchId],
  );

  const stopWhen = useCallback(
    (data: BatchDetail | null) => Boolean(data && TERMINAL_STATUSES.has(data.status)),
    [],
  );

  const poll = usePolling<BatchDetail | null>({
    fn,
    intervalMs: POLL_INTERVAL_MS,
    stopWhen,
    enabled: Boolean(batchId),
  });

  return {
    detail: poll.data,
    error: poll.error ? poll.error.message : null,
    isPolling: poll.isPolling,
    isPaused: poll.isPaused,
    lastUpdatedAt: poll.lastUpdatedAt,
    lastResponseMs: poll.lastResponseMs,
    pause: poll.pause,
    resume: poll.resume,
    refresh: poll.refresh,
  };
}
