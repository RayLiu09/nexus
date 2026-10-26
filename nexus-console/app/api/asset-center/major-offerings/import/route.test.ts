import { afterEach, expect, it, vi } from "vitest";
import { POST } from "./route";

const { cookieStore, fetchMock } = vi.hoisted(() => ({ cookieStore: vi.fn(), fetchMock: vi.fn() }));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: cookieStore }) }));
vi.mock("@/lib/api", () => ({ apiBaseUrl: () => "http://api.test" }));
afterEach(() => { vi.resetAllMocks(); vi.unstubAllGlobals(); });

it("forwards the actual multipart file and key using only the server session", async () => {
  vi.stubGlobal("fetch", fetchMock);
  cookieStore.mockReturnValue({ value: "server-token" });
  fetchMock.mockResolvedValue(Response.json({ data: { imported_count: 2 } }));
  const form = new FormData();
  const file = new File(["excel"], "布点.xlsx");
  form.set("file", file);
  const request = { formData: async () => form, headers: new Headers({ "idempotency-key": "operation-1" }) } as Request;
  const result = await POST(request);
  expect(result.status).toBe(200);
  expect(await result.json()).toEqual({ data: { imported_count: 2 } });
  expect(fetchMock).toHaveBeenCalledWith("http://api.test/internal/v1/major-offerings/import", {
    method: "POST", headers: { authorization: "Bearer server-token", "idempotency-key": "operation-1" }, body: form, cache: "no-store",
  });
});

it("rejects unauthenticated requests before reading or forwarding the file", async () => {
  vi.stubGlobal("fetch", fetchMock);
  cookieStore.mockReturnValue(undefined);
  const result = await POST({} as Request);
  expect(result.status).toBe(401);
  expect(fetchMock).not.toHaveBeenCalled();
});
