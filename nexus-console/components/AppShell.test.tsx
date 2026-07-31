import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { AppShell } from "./AppShell";

vi.mock("@/components/QuickUploadProvider", () => ({
  QuickUploadProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/Sidebar", () => ({
  Sidebar: ({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) => (
    <button type="button" aria-label="切换侧边栏" data-collapsed={String(collapsed)} onClick={onToggle}>
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
  it("toggles the collapsed class when the sidebar is collapsed and expanded", async () => {
    const user = userEvent.setup();
    const { container } = render(<AppShell><p>页面内容</p></AppShell>);
    const shell = container.querySelector(".app-shell");

    expect(shell).not.toBeNull();
    expect(shell).not.toHaveClass("collapsed");

    await user.click(screen.getByRole("button", { name: "切换侧边栏" }));

    expect(shell).toHaveClass("app-shell", "collapsed");
    expect(screen.getByRole("button", { name: "切换侧边栏" })).toHaveAttribute(
      "data-collapsed", "true",
    );

    await user.click(screen.getByRole("button", { name: "切换侧边栏" }));

    expect(shell).toHaveClass("app-shell");
    expect(shell).not.toHaveClass("collapsed");
    expect(screen.getByRole("button", { name: "切换侧边栏" })).toHaveAttribute(
      "data-collapsed", "false",
    );
  });
});
