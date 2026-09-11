import { App as AntApp } from "antd";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LoginPage from "./page";

const navigationMocks = vi.hoisted(() => ({
  redirect: null as string | null,
  replace: vi.fn(),
  refresh: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    replace: navigationMocks.replace,
    refresh: navigationMocks.refresh,
  }),
  useSearchParams: () => ({
    get: (name: string) => (name === "redirect" ? navigationMocks.redirect : null),
  }),
}));

function renderLoginPage() {
  return render(
    <AntApp>
      <LoginPage />
    </AntApp>,
  );
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("LoginPage", () => {
  beforeEach(() => {
    navigationMocks.redirect = null;
    navigationMocks.replace.mockReset();
    navigationMocks.refresh.mockReset();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
  });

  it("renders the NEXUS brand, login form, and two supported Console roles", async () => {
    renderLoginPage();

    expect(screen.getByRole("img", { name: "NEXUS Logo" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "NEXUS" })).toBeInTheDocument();
    expect(screen.getByText("企业数据与知识资产平台")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 2, name: "账户登录" })).toBeInTheDocument();
    expect(screen.getByText("数据管理员")).toBeInTheDocument();
    expect(screen.getByText("业务专家")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("请输入用户名")).toHaveAttribute("autocomplete", "username");
    expect(screen.getByPlaceholderText("请输入密码")).toHaveAttribute(
      "autocomplete",
      "current-password",
    );
  });

  it("validates required account credentials before submission", async () => {
    const user = userEvent.setup();
    renderLoginPage();

    await user.click(await screen.findByRole("button", { name: "登录" }));

    expect(await screen.findByText("请输入用户名")).toBeInTheDocument();
    expect(await screen.findByText("请输入密码")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([request]) => request === "/api/auth/login")).toBe(
      false,
    );
  });

  it("shows the server authorization error without redirecting", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn((request: RequestInfo | URL) =>
      Promise.resolve(
        request === "/api/auth/login"
          ? jsonResponse({ error: { message: "该账号不具备 Console 登录权限" } }, 403)
          : new Response(null, { status: 204 }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderLoginPage();

    await user.type(await screen.findByPlaceholderText("请输入用户名"), "api_caller");
    await user.type(screen.getByPlaceholderText("请输入密码"), "not-a-console-user");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("该账号不具备 Console 登录权限");
    expect(navigationMocks.replace).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/login",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ username: "api_caller", password: "not-a-console-user" }),
      }),
    );
  });

  it("redirects a successful login to the safe requested Console route", async () => {
    const user = userEvent.setup();
    navigationMocks.redirect = "/governance";
    vi.stubGlobal(
      "fetch",
      vi.fn((request: RequestInfo | URL) =>
        Promise.resolve(
          request === "/api/auth/login"
            ? jsonResponse({
                data: { displayName: "数据管理员" },
                meta: { trace_id: "trace-login" },
              })
            : new Response(null, { status: 204 }),
        ),
      ),
    );
    renderLoginPage();

    await user.type(await screen.findByPlaceholderText("请输入用户名"), "platform_data_admin");
    await user.type(screen.getByPlaceholderText("请输入密码"), "password");
    await user.click(screen.getByRole("button", { name: "登录" }));

    await waitFor(() => expect(navigationMocks.replace).toHaveBeenCalledWith("/governance"));
    expect(navigationMocks.refresh).toHaveBeenCalled();
  });

  it("redirects an existing session without exposing the credential form", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ data: { role: "business_expert" } })),
    );
    renderLoginPage();

    await waitFor(() => expect(navigationMocks.replace).toHaveBeenCalledWith("/workbench"));
    expect(screen.queryByPlaceholderText("请输入用户名")).not.toBeInTheDocument();
    expect(navigationMocks.refresh).toHaveBeenCalled();
  });
});
