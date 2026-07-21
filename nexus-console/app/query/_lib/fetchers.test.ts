/**
 * B8 tests — fetchQueryRouterAnswer envelope handling.
 *
 * The proxy layer wraps every response in `{ok, status, data}` /
 * `{ok:false, message}`; the fetcher must unwrap success and throw
 * on failure so callers only reason about the domain payload.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import { fetchQueryRouterAnswer } from "./fetchers";
import type { QueryRouterResponse } from "./queryTypes";

const okResponse: QueryRouterResponse = {
  markdown: "# 结果",
  intent: "scenario_1",
  intent_confidence: 0.92,
  invoked_tools: ["internal.search_chunks_by_semantic"],
  fallback_reason: null,
  warnings: [],
  audit_summary: { query_route: "v2" },
  external_web_results: [],
};

describe("fetchQueryRouterAnswer", () => {
  const originalFetch = globalThis.fetch;
  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("returns unwrapped data on ok envelope", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      json: async () => ({ ok: true, status: 200, data: okResponse, traceId: "t1" }),
    });
    const result = await fetchQueryRouterAnswer("跨境电商");
    expect(result).toEqual(okResponse);
    const call = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[0]).toBe("/api/query");
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(call[1].body as string)).toEqual({ query: "跨境电商" });
  });

  it("throws Error with server message on failure envelope", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      json: async () => ({ ok: false, status: 400, message: "问题 query 不能为空" }),
    });
    await expect(fetchQueryRouterAnswer("")).rejects.toThrow(/query 不能为空/);
  });

  it("falls back to HTTP code text when server omits message", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      status: 502,
      json: async () => ({ ok: false, status: 502, message: "" }),
    });
    await expect(fetchQueryRouterAnswer("q")).rejects.toThrow(/HTTP 502/);
  });
});
