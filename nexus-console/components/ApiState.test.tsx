import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiState } from "@/components/ApiState";

describe("ApiState", () => {
  it("renders nothing when ok=true", () => {
    const { container } = render(<ApiState ok error={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows unavailable alert when ok=false", () => {
    render(<ApiState ok={false} error="Connection refused" />);
    expect(screen.getByText("API 不可用")).toBeInTheDocument();
  });

  it("displays error message in description", () => {
    render(<ApiState ok={false} error="Network Error" />);
    expect(screen.getByText("Network Error")).toBeInTheDocument();
  });

  it("displays traceId when provided", () => {
    render(<ApiState ok={false} error="fail" traceId="abc12345" />);
    expect(screen.getByText("trace: abc12345")).toBeInTheDocument();
  });

  it("shows retry button when onRetry provided", async () => {
    const onRetry = vi.fn();
    render(<ApiState ok={false} error="fail" onRetry={onRetry} />);
    const btn = screen.getByRole("button", { name: /重\s*试/ });
    expect(btn).toBeInTheDocument();
    await userEvent.click(btn);
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("does not show retry button when onRetry is omitted", () => {
    render(<ApiState ok={false} error="fail" />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("uses generic message when error is null", () => {
    render(<ApiState ok={false} error={null} />);
    expect(screen.getByText("无法连接到后端服务")).toBeInTheDocument();
  });
});
