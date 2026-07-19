/**
 * SSE consumer tests — useQueryRouterStream.
 *
 * We stub `globalThis.fetch` to return a ReadableStream that emits
 * scripted SSE frames, then assert the hook state after the stream
 * ends. React's `act` isn't needed because the hook exposes plain
 * async methods that resolve after all state updates settle.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

import { useQueryRouterStream } from "./useQueryRouterStream";

function buildStreamResponse(frames: string[]): Response {
  const encoder = new TextEncoder();
  const chunks = frames.map((f) => encoder.encode(f));
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(chunk);
      }
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

function sse(event: string, data: object): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

describe("useQueryRouterStream", () => {
  const originalFetch = globalThis.fetch;
  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("accumulates chunk text and swaps in final markdown on 'final'", async () => {
    const finalPayload = {
      markdown: "# 最终\n\n完整替换后",
      raw_markdown: "# 最终\n\n完整替换后",
      intent: "scenario_1",
      intent_confidence: 0.9,
      invoked_tools: ["internal.search_chunks_by_semantic"],
      fallback_reason: null,
      warnings: [],
      audit_summary: { query_route: "v2" },
    };
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      buildStreamResponse([
        sse("meta", { intent: "scenario_1", intent_confidence: 0.9 }),
        sse("chunk", { text: "# 汇总" }),
        sse("chunk", { text: "\n\n内容" }),
        sse("final", finalPayload),
        sse("done", {}),
      ]),
    );

    const { result } = renderHook(() => useQueryRouterStream());
    await act(async () => {
      await result.current.start("跨境电商");
    });
    await waitFor(() => {
      expect(result.current.state.status).toBe("success");
    });

    expect(result.current.state.rawMarkdown).toBe("# 汇总\n\n内容");
    expect(result.current.state.result?.markdown).toBe("# 最终\n\n完整替换后");
    expect(result.current.state.meta?.intent).toBe("scenario_1");
  });

  it("survives frames split across TCP reads", async () => {
    // The `chunk` frame here is split mid-payload — the hook's buffer
    // must reassemble before parsing (real streams routinely deliver
    // partial frames).
    const finalPayload = {
      markdown: "ok",
      raw_markdown: "ok",
      intent: "scenario_1",
      intent_confidence: 0.9,
      invoked_tools: [],
      fallback_reason: null,
      warnings: [],
      audit_summary: {},
    };
    const rawEvents =
      sse("chunk", { text: "第一段" }) +
      sse("chunk", { text: "第二段" }) +
      sse("final", finalPayload) +
      sse("done", {});
    // Split into three physical TCP-ish chunks that don't respect
    // frame boundaries.
    const third = Math.floor(rawEvents.length / 3);
    const frames = [
      rawEvents.slice(0, third),
      rawEvents.slice(third, third * 2),
      rawEvents.slice(third * 2),
    ];
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      buildStreamResponse(frames),
    );

    const { result } = renderHook(() => useQueryRouterStream());
    await act(async () => {
      await result.current.start("q");
    });
    await waitFor(() => {
      expect(result.current.state.status).toBe("success");
    });
    expect(result.current.state.rawMarkdown).toBe("第一段第二段");
  });

  it("records error frames as warnings without ending the stream", async () => {
    const finalPayload = {
      markdown: "> ⚠️ fallback",
      raw_markdown: "> ⚠️ fallback",
      intent: "scenario_1",
      intent_confidence: 0.9,
      invoked_tools: [],
      fallback_reason: "llm_call_failed",
      warnings: ["rate_limit"],
      audit_summary: {},
    };
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      buildStreamResponse([
        sse("meta", {}),
        sse("error", { reason: "llm_call_failed" }),
        sse("final", finalPayload),
        sse("done", {}),
      ]),
    );

    const { result } = renderHook(() => useQueryRouterStream());
    await act(async () => {
      await result.current.start("q");
    });
    await waitFor(() => {
      expect(result.current.state.status).toBe("success");
    });
    expect(result.current.state.warnings).toContain("rate_limit");
    expect(result.current.state.result?.fallback_reason).toBe("llm_call_failed");
  });

  it("sets status=error when HTTP proxy returns non-200", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: false, status: 401, message: "未登录" }), {
        status: 401,
        headers: { "content-type": "application/json" },
      }),
    );
    const { result } = renderHook(() => useQueryRouterStream());
    await act(async () => {
      await result.current.start("q");
    });
    await waitFor(() => {
      expect(result.current.state.status).toBe("error");
    });
    expect(result.current.state.error).toBe("未登录");
  });

  it("done without final marks status=error", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      buildStreamResponse([sse("meta", {}), sse("done", {})]),
    );
    const { result } = renderHook(() => useQueryRouterStream());
    await act(async () => {
      await result.current.start("q");
    });
    await waitFor(() => {
      expect(result.current.state.status).toBe("error");
    });
  });
});
