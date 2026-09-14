import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";

import { middleware } from "./middleware";

function accessToken(role: string): string {
  const encode = (value: object) => Buffer.from(JSON.stringify(value)).toString("base64url");
  return `${encode({ alg: "none", typ: "JWT" })}.${encode({ sub: "user-1", role })}.signature`;
}

function pageRequest(pathname: string, role: string): NextRequest {
  return new NextRequest(`http://localhost${pathname}`, {
    headers: { cookie: `nexus_access_token=${accessToken(role)}` },
  });
}

describe("Console middleware role boundary", () => {
  it("allows the login background image without a Console session", () => {
    const response = middleware(
      new NextRequest("http://localhost/images/nexus-login-background.svg"),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("serves role avatars without a Console session", () => {
    const response = middleware(
      new NextRequest("http://localhost/avatars/data-admin.svg"),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it.each(["ops", "api_caller"])(
    "redirects backend role %s and clears auth cookies",
    (role) => {
      const response = middleware(pageRequest("/ai-prompts", role));
      const setCookie = response.headers.get("set-cookie") ?? "";

      expect(response.status).toBe(307);
      expect(response.headers.get("location")).toBe(
        "http://localhost/login?redirect=%2Fai-prompts",
      );
      expect(setCookie).toContain("nexus_access_token=");
      expect(setCookie).toContain("nexus_refresh_token=");
      expect(setCookie).toContain("Max-Age=0");
    },
  );

  it("lets platform_data_admin reach admin-only routes", () => {
    const response = middleware(pageRequest("/data-sources", "platform_data_admin"));
    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("redirects platform_data_admin away from expert-only /ai-prompts", () => {
    const response = middleware(pageRequest("/ai-prompts", "platform_data_admin"));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost/workbench");
  });

  it("lets business_expert reach expert-only /asset-center", () => {
    const response = middleware(pageRequest("/asset-center", "business_expert"));
    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("redirects business_expert away from admin-only /data-sources", () => {
    const response = middleware(pageRequest("/data-sources", "business_expert"));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost/asset-center");
  });

  it("redirects business_expert away from admin-only /users", () => {
    const response = middleware(pageRequest("/users", "business_expert"));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost/asset-center");
  });

  it("redirects root `/` to each role's landing page", () => {
    const adminResp = middleware(pageRequest("/", "platform_data_admin"));
    expect(adminResp.status).toBe(307);
    expect(adminResp.headers.get("location")).toBe("http://localhost/workbench");

    const expertResp = middleware(pageRequest("/", "business_expert"));
    expect(expertResp.status).toBe(307);
    expect(expertResp.headers.get("location")).toBe("http://localhost/asset-center");
  });
});
