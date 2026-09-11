import { beforeEach, describe, expect, it, vi } from "vitest";

import { proxy } from "@/lib/api/proxy";
import { POST } from "./route";

vi.mock("@/lib/api/proxy", () => ({ proxy: vi.fn() }));

function backendLogin(role: string) {
  return {
    ok: true as const,
    status: 200,
    data: {
      access_token: "access-token",
      refresh_token: "refresh-token",
      token_type: "bearer" as const,
      user: {
        id: "user-1",
        username: "test-user",
        display_name: "Test User",
        role,
        org_id: "org-1",
        org_name: "Test Org",
        env: "demo",
      },
    },
    traceId: "trace-login",
    total: null,
    etag: null,
  };
}

function loginRequest(): Request {
  return new Request("http://localhost/api/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username: "test-user", password: "secret" }),
  });
}

describe("Console login role boundary", () => {
  beforeEach(() => vi.clearAllMocks());

  it.each(["ops", "api_caller"])("rejects backend role %s without setting cookies", async (role) => {
    vi.mocked(proxy).mockResolvedValue(backendLogin(role));

    const response = await POST(loginRequest());

    expect(response.status).toBe(403);
    await expect(response.json()).resolves.toEqual({
      error: { message: "该账号不具备 Console 登录权限" },
    });
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it.each(["platform_data_admin", "business_expert"])(
    "allows Console role %s and sets both auth cookies",
    async (role) => {
      vi.mocked(proxy).mockResolvedValue(backendLogin(role));

      const response = await POST(loginRequest());
      const setCookie = response.headers.get("set-cookie") ?? "";

      expect(response.status).toBe(200);
      expect((await response.json()).data.role).toBe(role);
      expect(setCookie).toContain("nexus_access_token=access-token");
      expect(setCookie).toContain("nexus_refresh_token=refresh-token");
    },
  );
});
