import { App as AntApp } from "antd";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { Topbar } from "./Topbar";

const sessionMocks = vi.hoisted(() => ({
  session: {
    id: "user-1",
    username: "platform_data_admin",
    displayName: "张敏",
    role: "platform_data_admin" as const,
    orgUnit: { id: "org-1", name: "产教融合中心" },
    env: "prod" as const,
    loggedInAt: Date.now(),
  },
}));

const logoutMock = vi.hoisted(() => vi.fn());
const quickUploadMock = vi.hoisted(() => ({ open: vi.fn() }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/workbench",
}));

vi.mock("@/lib/auth/useSession", () => ({
  useSession: () => ({ session: sessionMocks.session }),
}));

vi.mock("@/lib/auth/session", () => ({
  logout: logoutMock,
}));

vi.mock("@/components/QuickUploadProvider", () => ({
  useQuickUpload: () => quickUploadMock,
}));

function renderTopbar() {
  return render(
    <AntApp>
      <Topbar />
    </AntApp>,
  );
}

beforeAll(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

describe("Topbar account center", () => {
  it("shows a compact account trigger without exposing environment information", () => {
    renderTopbar();

    expect(screen.getByRole("button", { name: "打开账户信息中心" })).toBeInTheDocument();
    expect(screen.getByText("张敏")).toBeInTheDocument();
    expect(screen.getByText("平台数据管理员")).toBeInTheDocument();
    expect(screen.queryByText(/环境/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Demo|Staging|生产/)).not.toBeInTheDocument();
  });

  it("opens account details and the change-password form", async () => {
    const user = userEvent.setup();
    renderTopbar();

    await user.click(screen.getByRole("button", { name: "打开账户信息中心" }));
    expect(await screen.findByRole("dialog", { name: "账户信息中心" })).toBeInTheDocument();
    expect(screen.getByText("产教融合中心")).toBeInTheDocument();
    expect(screen.getByText("已登录")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "修改密码" }));

    expect(await screen.findByRole("dialog", { name: "修改密码" })).toBeInTheDocument();
    expect(screen.getByLabelText("当前密码")).toBeInTheDocument();
    expect(screen.getByLabelText("新密码")).toBeInTheDocument();
    expect(screen.getByLabelText("确认新密码")).toBeInTheDocument();
    // Explanatory hint replaces the previous "尚未接入" demo alert.
    expect(
      screen.getByText("验证当前密码后设置新密码，后续登录将使用新密码。"),
    ).toBeInTheDocument();
  });

  it("validates password confirmation locally without calling the API", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    renderTopbar();

    await user.click(screen.getByRole("button", { name: "打开账户信息中心" }));
    await user.click(screen.getByRole("button", { name: "修改密码" }));
    await user.type(screen.getByLabelText("当前密码"), "current-pass");
    await user.type(screen.getByLabelText("新密码"), "new-password");
    await user.type(screen.getByLabelText("确认新密码"), "different-password");
    await user.click(screen.getByRole("button", { name: "确认修改" }));

    expect(await screen.findByText("两次输入的新密码不一致")).toBeInTheDocument();
    // Local Antd Form validation must reject before hitting the network.
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("posts to /api/auth/change-password when the form is valid", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ data: { ok: true }, meta: { trace_id: "trace-1" } }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    renderTopbar();

    await user.click(screen.getByRole("button", { name: "打开账户信息中心" }));
    await user.click(screen.getByRole("button", { name: "修改密码" }));
    await user.type(screen.getByLabelText("当前密码"), "OldPass1234");
    await user.type(screen.getByLabelText("新密码"), "NewPass1234");
    await user.type(screen.getByLabelText("确认新密码"), "NewPass1234");
    await user.click(screen.getByRole("button", { name: "确认修改" }));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe("/api/auth/change-password");
    const body = JSON.parse((init?.body as string) ?? "{}");
    expect(body).toEqual({
      current_password: "OldPass1234",
      new_password: "NewPass1234",
    });
    fetchSpy.mockRestore();
  });

  it("keeps logout delegated to the existing session helper", async () => {
    const user = userEvent.setup();
    renderTopbar();

    await user.click(screen.getByRole("button", { name: "打开账户信息中心" }));
    await user.click(screen.getByRole("button", { name: "退出登录" }));

    await waitFor(() => expect(logoutMock).toHaveBeenCalledTimes(1));
  });
});
