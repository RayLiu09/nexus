"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Generic polling hook used across NX-05 jobs, NX-03 sync detail, ingest
 * batch tracking, etc.
 *
 * v3.2 §10.5 contract:
 *   - 自适应间隔（默认 5s；调用方传 3s 用于详情页）
 *   - 标签切走自动暂停（page-visibility），切回继续
 *   - 网络错误 1s / 3s / 9s 退避；达到上限标 error 但不停（手动 refresh 仍可用）
 *   - 终态调用方可通过 `stopWhen` 自停（如 job.status ∈ succeeded/failed）
 */
export interface UsePollingOptions<T> {
  fn: (signal: AbortSignal) => Promise<T>;
  intervalMs: number;
  /** 若返回 true 则不再继续轮询（终态停机）。 */
  stopWhen?: (data: T) => boolean;
  /** 标签切走自动暂停；默认 true。 */
  pauseOnHidden?: boolean;
  /** 退避序列（毫秒），缺省 [1_000, 3_000, 9_000]。 */
  backoffMs?: number[];
  /** 启用条件：false 时不发起请求（用于 batchId/jobId 尚未就绪场景）。 */
  enabled?: boolean;
  /** 后台标签页是否继续轮询；默认 false（切到后台即暂停）。 */
  refetchIntervalInBackground?: boolean;
}

export interface UsePollingResult<T> {
  data: T | null;
  error: Error | null;
  isPolling: boolean;
  isPaused: boolean;
  consecutiveFailures: number;
  /** epoch ms；从未成功为 null。 */
  lastUpdatedAt: number | null;
  /** 最近一次请求耗时 ms；从未成功为 null。 */
  lastResponseMs: number | null;
  pause: () => void;
  resume: () => void;
  /** 手动触发一次拉取（不影响下一次自动节奏）。 */
  refresh: () => void;
}

const DEFAULT_BACKOFF: ReadonlyArray<number> = [1_000, 3_000, 9_000];

/** 三级刷新频率（毫秒）— 生产就绪 P2.2 */
export const POLL_FAST = 30_000;    // 作业/ingest 状态
export const POLL_NORMAL = 60_000;  // 资产列表
export const POLL_SLOW = 300_000;   // 摘要统计

export function usePolling<T>(options: UsePollingOptions<T>): UsePollingResult<T> {
  const {
    fn,
    intervalMs,
    stopWhen,
    pauseOnHidden = true,
    backoffMs = DEFAULT_BACKOFF,
    enabled = true,
    refetchIntervalInBackground = false,
  } = options;

  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [isPaused, setIsPaused] = useState(false);
  const [isPolling, setIsPolling] = useState(false);
  const [consecutiveFailures, setConsecutiveFailures] = useState(0);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  const [lastResponseMs, setLastResponseMs] = useState<number | null>(null);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const stoppedRef = useRef(false);
  const failuresRef = useRef(0);
  const fnRef = useRef(fn);
  const stopWhenRef = useRef(stopWhen);
  const isPausedRef = useRef(isPaused);
  const intervalMsRef = useRef(intervalMs);
  const backoffRef = useRef(backoffMs);
  // schedule 需要在 setTimeout 回调里递归引用自己；用 ref 打破循环。
  const scheduleRef = useRef<() => void>(() => {});

  // 保持最新引用，避免 effect 因每次渲染重订阅。
  useEffect(() => {
    fnRef.current = fn;
  }, [fn]);
  useEffect(() => {
    stopWhenRef.current = stopWhen;
  }, [stopWhen]);
  useEffect(() => {
    isPausedRef.current = isPaused;
  }, [isPaused]);
  useEffect(() => {
    intervalMsRef.current = intervalMs;
  }, [intervalMs]);
  useEffect(() => {
    backoffRef.current = backoffMs;
  }, [backoffMs]);

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const computeNextDelay = useCallback((failures: number): number => {
    if (failures <= 0) return intervalMsRef.current;
    const seq = backoffRef.current;
    const idx = Math.min(failures - 1, seq.length - 1);
    return seq[idx];
  }, []);

  const runOnce = useCallback(async () => {
    if (stoppedRef.current) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setIsPolling(true);
    const startedAt = Date.now();
    try {
      const result = await fnRef.current(controller.signal);
      if (controller.signal.aborted) return;
      setData(result);
      setError(null);
      failuresRef.current = 0;
      setConsecutiveFailures(0);
      setLastUpdatedAt(Date.now());
      setLastResponseMs(Date.now() - startedAt);
      if (stopWhenRef.current?.(result)) {
        stoppedRef.current = true;
        setIsPolling(false);
        clearTimer();
        return;
      }
    } catch (err) {
      if (controller.signal.aborted) return;
      const e = err instanceof Error ? err : new Error(String(err));
      setError(e);
      failuresRef.current += 1;
      setConsecutiveFailures(failuresRef.current);
      setLastResponseMs(Date.now() - startedAt);
    } finally {
      if (!controller.signal.aborted) setIsPolling(false);
    }
  }, [clearTimer]);

  // 通过 ref 安装 schedule 实现，避免 useCallback 间循环依赖。
  // useEffect 在 mount/commit 阶段安装，避免在 render 阶段修改 ref。
  useEffect(() => {
    scheduleRef.current = () => {
      clearTimer();
      if (stoppedRef.current) return;
      if (isPausedRef.current) return;
      const delay = computeNextDelay(failuresRef.current);
      timerRef.current = setTimeout(async () => {
        await runOnce();
        scheduleRef.current();
      }, delay);
    };
  }, [clearTimer, computeNextDelay, runOnce]);

  const startLoop = useCallback(() => {
    void (async () => {
      await runOnce();
      scheduleRef.current();
    })();
  }, [runOnce]);

  // 启动 / 重启 / 终止主循环（仅在 enabled 变更时）
  useEffect(() => {
    if (!enabled) {
      clearTimer();
      abortRef.current?.abort();
      stoppedRef.current = true;
      return;
    }
    stoppedRef.current = false;
    failuresRef.current = 0;
    startLoop();
    return () => {
      stoppedRef.current = true;
      clearTimer();
      abortRef.current?.abort();
    };
  }, [enabled, clearTimer, startLoop]);

  // 暂停 / 恢复 — 仅在用户主动切换 isPaused 时介入
  useEffect(() => {
    if (isPaused) {
      clearTimer();
      abortRef.current?.abort();
      return;
    }
    if (!enabled || stoppedRef.current) return;
    startLoop();
  }, [isPaused, enabled, clearTimer, startLoop]);

  // 标签切走暂停（不影响用户主动 pause/resume 的状态）
  // refetchIntervalInBackground 为 true 时跳过可见性暂停。
  useEffect(() => {
    if (!pauseOnHidden || refetchIntervalInBackground) return;
    if (typeof document === "undefined") return;
    const onVisibility = () => {
      if (document.hidden) {
        clearTimer();
        abortRef.current?.abort();
      } else if (!isPausedRef.current && enabled && !stoppedRef.current) {
        startLoop();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [pauseOnHidden, refetchIntervalInBackground, enabled, clearTimer, startLoop]);

  const pause = useCallback(() => setIsPaused(true), []);
  const resume = useCallback(() => setIsPaused(false), []);
  const refresh = useCallback(() => {
    void runOnce();
  }, [runOnce]);

  return {
    data,
    error,
    isPolling,
    isPaused,
    consecutiveFailures,
    lastUpdatedAt,
    lastResponseMs,
    pause,
    resume,
    refresh,
  };
}
