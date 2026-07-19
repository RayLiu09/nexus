"use client";

/**
 * SSE consumer for POST /api/query/stream.
 *
 * Exposes a small reducer state that mirrors the SSE lifecycle:
 * ``idle`` → ``running`` → ``success | error``. Chunks accumulate into
 * ``rawMarkdown`` (with `[[CHART:xxx]]` placeholders still visible);
 * when the ``final`` frame lands we replace ``result`` and the UI
 * switches to render the fully-swapped markdown. ``done`` unlocks
 * ``running`` regardless of whether a ``final`` fired (defensive
 * against a truncated stream — the UI still shows whatever chunks
 * accumulated).
 *
 * Cancellation: ``reset()`` aborts the in-flight fetch via
 * ``AbortController`` so switching queries mid-stream doesn't leak.
 */
import { useCallback, useRef, useState } from "react";

import type { QueryRouterResponse } from "./queryTypes";

export type StreamStatus = "idle" | "running" | "success" | "error";

interface StreamMeta {
  intent?: string;
  intent_confidence?: number;
  invoked_tools?: string[];
  chart_ids?: string[];
  fallback_reason?: string;
  dispatch_fallback?: string;
  template_id?: string;
}

export interface UseQueryRouterStreamState {
  status: StreamStatus;
  meta: StreamMeta | null;
  rawMarkdown: string;
  result: QueryRouterResponse | null;
  error: string | null;
  warnings: string[];
}

const INITIAL_STATE: UseQueryRouterStreamState = {
  status: "idle",
  meta: null,
  rawMarkdown: "",
  result: null,
  error: null,
  warnings: [],
};

export interface UseQueryRouterStream {
  state: UseQueryRouterStreamState;
  start: (query: string) => Promise<void>;
  reset: () => void;
}

const STREAM_ENDPOINT = "/api/query/stream";

export function useQueryRouterStream(): UseQueryRouterStream {
  const [state, setState] = useState<UseQueryRouterStreamState>(INITIAL_STATE);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setState(INITIAL_STATE);
  }, []);

  const start = useCallback(async (query: string) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setState({ ...INITIAL_STATE, status: "running" });

    let response: Response;
    try {
      response = await fetch(STREAM_ENDPOINT, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ query }),
        signal: controller.signal,
        cache: "no-store",
      });
    } catch (err) {
      if (controller.signal.aborted) return;
      setState((prev) => ({
        ...prev,
        status: "error",
        error: err instanceof Error ? err.message : "网络错误",
      }));
      return;
    }

    if (!response.ok || !response.body) {
      const message = await safeErrorMessage(response);
      setState((prev) => ({
        ...prev,
        status: "error",
        error: message,
      }));
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = extractFrames(buffer);
        buffer = frames.remainder;
        for (const frame of frames.parsed) {
          applyFrame(frame, setState);
        }
      }
    } catch (err) {
      if (controller.signal.aborted) return;
      setState((prev) => ({
        ...prev,
        status: "error",
        error: err instanceof Error ? err.message : "读取流失败",
      }));
      return;
    }
  }, []);

  return { state, start, reset };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface SseFrame {
  event: string;
  data: string;
}

interface FrameParseResult {
  parsed: SseFrame[];
  remainder: string;
}

function extractFrames(buffer: string): FrameParseResult {
  // SSE frames terminate on `\n\n`. We split on that boundary and keep
  // any trailing partial frame in the remainder so the next chunk can
  // complete it.
  const parts = buffer.split("\n\n");
  const remainder = parts.pop() ?? "";
  const parsed: SseFrame[] = [];
  for (const raw of parts) {
    const frame = parseFrame(raw);
    if (frame) parsed.push(frame);
  }
  return { parsed, remainder };
}

function parseFrame(raw: string): SseFrame | null {
  let event = "message";
  let data = "";
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      // Multi-line ``data:`` fields join with newlines per the SSE spec;
      // our backend emits single-line JSON so simple concat is fine.
      data =
        data === ""
          ? line.slice("data:".length).trim()
          : `${data}\n${line.slice("data:".length).trim()}`;
    }
  }
  if (!event && !data) return null;
  return { event, data };
}

type ApplyFrame = (update: (prev: UseQueryRouterStreamState) => UseQueryRouterStreamState) => void;

function applyFrame(frame: SseFrame, setState: ApplyFrame): void {
  const parsed = safeParseJson(frame.data);
  switch (frame.event) {
    case "meta":
      setState((prev) => ({ ...prev, meta: parsed as StreamMeta }));
      return;
    case "chunk": {
      const text = typeof parsed?.text === "string" ? parsed.text : "";
      setState((prev) => ({ ...prev, rawMarkdown: prev.rawMarkdown + text }));
      return;
    }
    case "final": {
      const result = parsed as QueryRouterResponse | null;
      setState((prev) => ({
        ...prev,
        result,
        warnings: result?.warnings ?? [],
      }));
      return;
    }
    case "error": {
      const reason = typeof parsed?.reason === "string" ? parsed.reason : "unknown";
      setState((prev) => ({
        ...prev,
        warnings: [...prev.warnings, reason],
      }));
      return;
    }
    case "done": {
      setState((prev) => ({
        ...prev,
        status: prev.result ? "success" : "error",
        error: prev.result ? null : (prev.error ?? "服务未返回有效结果"),
      }));
      return;
    }
    default:
      return;
  }
}

// A safe JSON.parse that shrugs on invalid payloads — SSE consumers
// should never crash on a malformed frame, only skip it.
function safeParseJson(raw: string): Record<string, unknown> | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return null;
  }
}

async function safeErrorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { message?: string };
    if (body && typeof body.message === "string" && body.message) return body.message;
  } catch {
    // fall through
  }
  return `HTTP ${response.status}`;
}
