import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test-utils/test-renderer";
import { Card } from "./Card";

describe("Card", () => {
  it("renders children in default variant", () => {
    renderWithProviders(<Card>Hello</Card>);
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });

  it("renders metric variant with label and value", () => {
    renderWithProviders(<Card variant="metric" label="总数" value={42} />);
    expect(screen.getByText("总数")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("renders hero variant with label, value, and sub", () => {
    renderWithProviders(<Card variant="hero" label="已完成" value={128} sub="较昨日 +12%" />);
    expect(screen.getByText("已完成")).toBeInTheDocument();
    expect(screen.getByText("128")).toBeInTheDocument();
    expect(screen.getByText("较昨日 +12%")).toBeInTheDocument();
  });

  it("applies weight classes", () => {
    renderWithProviders(<Card weight="primary">P</Card>);
    const el = screen.getByText("P").closest(".card");
    expect(el?.className).toContain("card--primary");
  });

  it("applies tone class for warning", () => {
    renderWithProviders(<Card variant="metric" tone="warning" label="待处理" value={5} />);
    const el = screen.getByText("5").closest(".card");
    expect(el?.className).toContain("card--warning");
  });

  it("applies tone class for danger", () => {
    renderWithProviders(<Card variant="metric" tone="danger" label="失败" value={3} />);
    const el = screen.getByText("3").closest(".card");
    expect(el?.className).toContain("card--danger");
  });

  it("applies tone class for success", () => {
    renderWithProviders(<Card variant="metric" tone="success" label="成功" value={99} />);
    const el = screen.getByText("99").closest(".card");
    expect(el?.className).toContain("card--success");
  });

  it("default tone has no tone class", () => {
    renderWithProviders(<Card variant="metric" label="总数" value={10} />);
    const el = screen.getByText("10").closest(".card");
    expect(el?.className).not.toContain("card--warning");
    expect(el?.className).not.toContain("card--danger");
    expect(el?.className).not.toContain("card--success");
  });

  it("renders interactive variant with class", () => {
    renderWithProviders(<Card variant="interactive">Click me</Card>);
    const el = screen.getByText("Click me").closest(".card");
    expect(el?.className).toContain("card--interactive");
  });
});
