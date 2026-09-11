import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";

import { middleware } from "./middleware";

function accessToken(role: string): string {
  const encode = (value: object) => Buffer.from(JSON.stringify(value)).toString("base64url");
  return `${encode({ alg: "none", typ: "JWT" })}.${encode({ sub: "user-1", role })}.signature`;
}

function pageRequest(role: string): NextRequest {
  return new NextRequest("http://localhost/ai-prompts", {
    headers: { cookie: `nexus_access_token=${accessToken(role)}` },
  });
}

describe("Console middleware role boundary", () => {
  it.each(["ops", "api_caller"])("redirects backend role %s and clears auth cookies", (role) => {
    const response = middleware(pageRequest(role));
    const setCookie = response.headers.get("set-cookie") ?? "";

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      "http://localhost/login?redirect=%2Fai-prompts",
    );
    expect(setCookie).toContain("nexus_access_token=");
    expect(setCookie).toContain("nexus_refresh_token=");
    expect(setCookie).toContain("Max-Age=0");
  });

  it.each(["platform_data_admin", "business_expert"])("allows Console role %s", (role) => {
    const response = middleware(pageRequest(role));

    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });
});
