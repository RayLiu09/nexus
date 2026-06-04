import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test-utils/test-renderer";
import { ErrorState } from "./ErrorState";

describe("ErrorState", () => {
  it("renders title", () => {
    renderWithProviders(<ErrorState title="加载失败" />);
    expect(screen.getByText("加载失败")).toBeInTheDocument();
  });

  it("renders description", () => {
    renderWithProviders(<ErrorState title="错误" description="网络连接超时" />);
    expect(screen.getByText("网络连接超时")).toBeInTheDocument();
  });

  it("renders traceId with truncated display", () => {
    // shortTrace: length 16 > 12 → "…" + last 8 chars = "…34567890"
    renderWithProviders(<ErrorState title="错误" traceId="abcdef1234567890" />);
    expect(screen.getByText(/…34567890/)).toBeInTheDocument();
  });

  it("renders retry button when onRetry provided", () => {
    renderWithProviders(<ErrorState title="错误" onRetry={() => {}} />);
    expect(screen.getByRole("button", { name: /重试/ })).toBeInTheDocument();
  });

  it("does not render retry button when onRetry omitted", () => {
    renderWithProviders(<ErrorState title="错误" />);
    expect(screen.queryByRole("button", { name: /重试/ })).not.toBeInTheDocument();
  });

  it("has role=alert for accessibility", () => {
    renderWithProviders(<ErrorState title="错误" />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("renders extra actions", () => {
    renderWithProviders(
      <ErrorState title="错误" extraActions={<button type="button">联系支持</button>} />,
    );
    expect(screen.getByRole("button", { name: "联系支持" })).toBeInTheDocument();
  });

  it("has a copy trace_id button when traceId is provided", () => {
    renderWithProviders(<ErrorState title="错误" traceId="trace-12345" />);
    expect(screen.getByLabelText("复制 trace_id")).toBeInTheDocument();
  });
});
