import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test-utils/test-renderer";
import { ConfirmButton } from "./ConfirmButton";

// Antd 6 adds whitespace between CJK characters in button text.
// Use a matcher that strips spaces from the accessible name before comparing.
function hasText(text: string) {
  return (_: string, el: Element | null) => {
    const name = (el as HTMLElement | null)?.textContent ?? "";
    return name.replace(/\s+/g, "") === text;
  };
}

describe("ConfirmButton", () => {
  it("renders trigger button", () => {
    renderWithProviders(
      <ConfirmButton title="删除确认" onConfirm={() => {}}>
        删除
      </ConfirmButton>,
    );
    expect(screen.getByRole("button", { name: hasText("删除") })).toBeInTheDocument();
  });

  it("opens modal on click", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <ConfirmButton title="确认操作" description="确定要执行吗？" onConfirm={() => {}}>
        操作
      </ConfirmButton>,
    );
    await user.click(screen.getByRole("button", { name: hasText("操作") }));
    expect(screen.getByText("确认操作")).toBeInTheDocument();
    expect(screen.getByText("确定要执行吗？")).toBeInTheDocument();
  });

  it("calls onConfirm when confirmed", async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderWithProviders(
      <ConfirmButton title="确认操作" onConfirm={onConfirm}>
        操作
      </ConfirmButton>,
    );
    await user.click(screen.getByRole("button", { name: hasText("操作") }));
    await user.click(screen.getByRole("button", { name: hasText("确认") }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("has cancel button that does not trigger onConfirm", async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderWithProviders(
      <ConfirmButton title="确认操作" onConfirm={onConfirm}>
        操作
      </ConfirmButton>,
    );
    await user.click(screen.getByRole("button", { name: hasText("操作") }));
    // Cancel button is present in modal
    expect(screen.getByRole("button", { name: hasText("取消") })).toBeInTheDocument();
    // onConfirm should not have been called yet (modal still open)
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("requires confirmWord typing before enabling confirm", async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderWithProviders(
      <ConfirmButton title="删除" confirmWord="DELETE" onConfirm={onConfirm}>
        删除
      </ConfirmButton>,
    );
    await user.click(screen.getByRole("button", { name: hasText("删除") }));

    const confirmBtn = screen.getByRole("button", { name: hasText("确认") });
    expect(confirmBtn).toBeDisabled();

    await user.type(screen.getByPlaceholderText("DELETE"), "DELETE");
    expect(confirmBtn).not.toBeDisabled();
  });

  it("supports danger prop on trigger button", () => {
    renderWithProviders(
      <ConfirmButton title="危险操作" danger onConfirm={() => {}}>
        删除
      </ConfirmButton>,
    );
    expect(screen.getByRole("button", { name: hasText("删除") })).toBeInTheDocument();
  });
});
