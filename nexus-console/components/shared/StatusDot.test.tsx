import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusDot } from "./StatusDot";
import type { StatusTone } from "./StatusDot";

const TONES: StatusTone[] = ["success", "info", "warning", "danger", "neutral"];

describe("StatusDot", () => {
  it.each(TONES)("renders with tone=%s", (tone) => {
    render(<StatusDot tone={tone}>{tone}</StatusDot>);
    const el = screen.getByRole("status");
    expect(el).toBeInTheDocument();
    expect(el).toHaveTextContent(tone);
  });

  it("has a colored dot (aria-hidden)", () => {
    const { container } = render(<StatusDot tone="success">OK</StatusDot>);
    const dot = container.querySelector('[aria-hidden="true"]');
    expect(dot).toBeInTheDocument();
    expect(dot?.tagName).toBe("SPAN");
  });

  it("sets aria-label from children string", () => {
    render(<StatusDot tone="danger">Failed</StatusDot>);
    expect(screen.getByRole("status")).toHaveAttribute("aria-label", "状态：Failed");
  });

  it("uses explicit ariaLabel when provided", () => {
    render(<StatusDot tone="info" ariaLabel="Custom label">Info</StatusDot>);
    expect(screen.getByRole("status")).toHaveAttribute("aria-label", "Custom label");
  });

  it("applies custom className", () => {
    render(<StatusDot tone="neutral" className="my-custom">text</StatusDot>);
    expect(screen.getByRole("status")).toHaveClass("my-custom");
  });

  it("renders all 5 tones with distinct colors", () => {
    const { container } = render(
      <>
        {TONES.map((t) => (
          <StatusDot key={t} tone={t}>{t}</StatusDot>
        ))}
      </>,
    );
    const dots = container.querySelectorAll('[aria-hidden="true"]');
    const colors = Array.from(dots).map((d) => (d as HTMLElement).style.background);
    const unique = new Set(colors);
    expect(unique.size).toBe(5);
  });
});
