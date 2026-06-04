import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusLabel } from "@/components/StatusLabel";

describe("StatusLabel", () => {
  it("renders known status with correct label", () => {
    render(<StatusLabel value="available" />);
    expect(screen.getByText("当前可用")).toBeInTheDocument();
  });

  it("renders fallback for unknown status value", () => {
    render(<StatusLabel value="unknown_status_xyz" />);
    expect(screen.getByText("unknown_status_xyz")).toBeInTheDocument();
  });

  it("overrides label when provided", () => {
    render(<StatusLabel value="available" label="自定义" />);
    expect(screen.getByText("自定义")).toBeInTheDocument();
  });

  it("applies correct CSS class for tone", () => {
    render(<StatusLabel value="failed" />);
    const el = screen.getByText("失败");
    expect(el.className).toContain("status-label-danger");
  });

  it("applies neutral tone class for unknown status", () => {
    render(<StatusLabel value="custom_status" />);
    const el = screen.getByText("custom_status");
    expect(el.className).toContain("status-label-neutral");
  });
});
