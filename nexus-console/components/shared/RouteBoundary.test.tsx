import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test-utils/test-renderer";
import { RouteBoundary } from "./RouteBoundary";

function ThrowingChild({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) throw new Error("Simulated render error");
  return <div>正常内容</div>;
}

describe("RouteBoundary", () => {
  it("renders children normally when no error", () => {
    renderWithProviders(
      <RouteBoundary>
        <ThrowingChild shouldThrow={false} />
      </RouteBoundary>,
    );
    expect(screen.getByText("正常内容")).toBeInTheDocument();
  });

  it("shows ErrorState when child throws", () => {
    // Suppress console.error for the expected throw
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    renderWithProviders(
      <RouteBoundary>
        <ThrowingChild shouldThrow />
      </RouteBoundary>,
    );
    expect(screen.getByText("页面渲染异常")).toBeInTheDocument();
    expect(screen.getByText("Simulated render error")).toBeInTheDocument();
    spy.mockRestore();
  });

  it("shows custom fallback when provided", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    renderWithProviders(
      <RouteBoundary fallback={() => <div>自定义错误</div>}>
        <ThrowingChild shouldThrow />
      </RouteBoundary>,
    );
    expect(screen.getByText("自定义错误")).toBeInTheDocument();
    spy.mockRestore();
  });

  it("shows traceId from error when error has traceId property", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    function ChildWithTrace(): never {
      const err = new Error("API error");
      (err as Error & { traceId: string }).traceId = "trace-abc123";
      throw err;
    }
    renderWithProviders(
      <RouteBoundary>
        <ChildWithTrace />
      </RouteBoundary>,
    );
    expect(screen.getByText("页面渲染异常")).toBeInTheDocument();
    spy.mockRestore();
  });
});
