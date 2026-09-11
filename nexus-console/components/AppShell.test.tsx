import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { AppShell } from "./AppShell";

const navigationMocks = vi.hoisted(() => ({ pathname: "/workbench" }));

vi.mock("next/navigation", () => ({
  usePathname: () => navigationMocks.pathname,
}));

vi.mock("@/components/QuickUploadProvider", () => ({
  QuickUploadProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/Sidebar", () => ({
  Sidebar: ({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) => (
    <button
      type="button"
      aria-label="切换侧边栏"
      data-collapsed={String(collapsed)}
      onClick={onToggle}
    >
      切换侧边栏
    </button>
  ),
}));

vi.mock("@/components/Topbar", () => ({
  Topbar: () => <header>Topbar</header>,
}));

vi.mock("@/components/shared/RouteBoundary", () => ({
  RouteBoundary: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

describe("AppShell", () => {
  it("renders the login route without the application navigation shell", () => {
    navigationMocks.pathname = "/login";

    const { container } = render(
      <AppShell>
        <p>登录页面</p>
      </AppShell>,
    );

    expect(screen.getByText("登录页面")).toBeInTheDocument();
    expect(screen.queryByText("Topbar")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "切换侧边栏" })).not.toBeInTheDocument();
    expect(container.querySelector(".app-shell")).toBeNull();
  });

  it("toggles the collapsed class when the sidebar is collapsed and expanded", async () => {
    navigationMocks.pathname = "/workbench";
    const user = userEvent.setup();
    const { container } = render(
      <AppShell>
        <p>页面内容</p>
      </AppShell>,
    );
    const shell = container.querySelector(".app-shell");

    expect(shell).not.toBeNull();
    expect(shell).not.toHaveClass("collapsed");

    await user.click(screen.getByRole("button", { name: "切换侧边栏" }));

    expect(shell).toHaveClass("app-shell", "collapsed");
    expect(screen.getByRole("button", { name: "切换侧边栏" })).toHaveAttribute(
      "data-collapsed",
      "true",
    );

    await user.click(screen.getByRole("button", { name: "切换侧边栏" }));

    expect(shell).toHaveClass("app-shell");
    expect(shell).not.toHaveClass("collapsed");
    expect(screen.getByRole("button", { name: "切换侧边栏" })).toHaveAttribute(
      "data-collapsed",
      "false",
    );
  });
});
