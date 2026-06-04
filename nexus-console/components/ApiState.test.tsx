import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ApiState } from "@/components/ApiState";

describe("ApiState", () => {
  it("shows connected message when ok=true", () => {
    render(<ApiState ok error={null} />);
    expect(screen.getByText("API 已连接")).toBeInTheDocument();
  });

  it("shows unavailable message when ok=false", () => {
    render(<ApiState ok={false} error="Connection refused" />);
    expect(screen.getByText("API 不可用")).toBeInTheDocument();
  });

  it("displays error message when provided", () => {
    render(<ApiState ok={false} error="Network Error" />);
    expect(screen.getByText("Network Error")).toBeInTheDocument();
  });

  it("does not show error when ok=true and no error", () => {
    const { container } = render(<ApiState ok error={null} />);
    expect(container.querySelector("strong")).not.toBeInTheDocument();
  });

  it("displays traceId when provided", () => {
    render(<ApiState ok error={null} traceId="abc12345" />);
    expect(screen.getByText("trace: abc12345")).toBeInTheDocument();
  });

  it("does not display traceId when null", () => {
    const { container } = render(<ApiState ok error={null} traceId={null} />);
    expect(container.querySelector(".mono-cell")).not.toBeInTheDocument();
  });

  it("applies error CSS class when !ok", () => {
    const { container } = render(<ApiState ok={false} error="fail" />);
    expect(container.querySelector(".api-state-error")).toBeInTheDocument();
  });

  it("applies ok CSS class when ok", () => {
    const { container } = render(<ApiState ok error={null} />);
    expect(container.querySelector(".api-state-ok")).toBeInTheDocument();
  });
});
