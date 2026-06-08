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

  it("renders antd card with small size for secondary weight", () => {
    renderWithProviders(<Card weight="secondary">S</Card>);
    const el =screen.getByText("S").closest(".ant-card");
    expect(el?.className).toContain("ant-card-small");
  });

  it("renders antd card with default size for primary weight", () => {
    renderWithProviders(<Card weight="primary">P</Card>);
    const el =screen.getByText("P").closest(".ant-card");
    expect(el).toBeTruthy();
  });

  it("applies warning tone via border color style", () => {
    renderWithProviders(<Card variant="metric" tone="warning" label="待处理" value={5} />);
    const el =screen.getByText("5").closest(".ant-card");
    expect(el).toBeTruthy();
  });

  it("applies danger tone via border color style", () => {
    renderWithProviders(<Card variant="metric" tone="danger" label="失败" value={3} />);
    const el =screen.getByText("3").closest(".ant-card");
    expect(el).toBeTruthy();
  });

  it("applies success tone via border color style", () => {
    renderWithProviders(<Card variant="metric" tone="success" label="成功" value={99} />);
    const el =screen.getByText("99").closest(".ant-card");
    expect(el).toBeTruthy();
  });

  it("renders interactive variant", () => {
    renderWithProviders(<Card variant="interactive">Click me</Card>);
    expect(screen.getByText("Click me")).toBeInTheDocument();
  });
});
