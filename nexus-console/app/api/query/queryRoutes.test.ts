import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { backendProxy } = vi.hoisted(() => ({ backendProxy: vi.fn() }));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: () => ({ value: "session-token" }) }) }));
vi.mock("@/lib/api", () => ({ apiBaseUrl: () => "http://backend.test" }));
vi.mock("@/lib/api/proxy", () => ({ proxy: backendProxy, pickResponseHeaders: () => ({}) }));

import { POST as streamPost } from "./stream/route";
import { POST as jsonPost } from "./route";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("event: done\ndata: {}\n\n", { headers: { "content-type": "text/event-stream" } })));
  backendProxy.mockResolvedValue({ ok: true, status: 200, data: {} });
});
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

describe.each([["stream", streamPost], ["json", jsonPost]] as const)("query %s proxy", (kind, post) => {
  it.each([undefined, false, true])("forwards an explicit boolean and defaults off: %s", async (flag) => {
    const response = await post(new Request("http://console.test/api/query", {
      method: "POST", body: JSON.stringify({ query: " 重庆政策 ", web_search: flag }),
    }));
    expect(response.status).toBe(200);
    const payload = kind === "stream"
      ? JSON.parse((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].body)
      : backendProxy.mock.calls[0][1].body;
    expect(payload).toEqual({ query: "重庆政策", web_search: flag ?? false });
  });

  it.each(["false", 1, null])("rejects non-boolean switches without contacting the backend: %s", async (flag) => {
    const response = await post(new Request("http://console.test/api/query", {
      method: "POST", body: JSON.stringify({ query: "政策", web_search: flag }),
    }));
    expect(response.status).toBe(400);
    expect(globalThis.fetch).not.toHaveBeenCalled();
    expect(backendProxy).not.toHaveBeenCalled();
  });
});
