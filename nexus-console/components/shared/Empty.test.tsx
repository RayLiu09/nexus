import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test-utils/test-renderer";
import { Empty } from "./Empty";

describe("Empty", () => {
  it("renders title", () => {
    renderWithProviders(<Empty title="还没有数据源" />);
    expect(screen.getByText("还没有数据源")).toBeInTheDocument();
  });

  it("renders description when provided", () => {
    renderWithProviders(<Empty title="无数据" description="创建第一个数据源以开始接入" />);
    expect(screen.getByText("创建第一个数据源以开始接入")).toBeInTheDocument();
  });

  it("renders no description when omitted", () => {
    renderWithProviders(<Empty title="无数据" />);
    expect(screen.queryByText("创建")).not.toBeInTheDocument();
  });

  it("renders actions when provided", () => {
    renderWithProviders(
      <Empty title="无数据" actions={<button type="button">创建</button>} />,
    );
    expect(screen.getByRole("button", { name: "创建" })).toBeInTheDocument();
  });

  it("has role=status for accessibility", () => {
    renderWithProviders(<Empty title="无数据" />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("applies custom className", () => {
    renderWithProviders(<Empty title="无数据" className="my-empty" />);
    expect(screen.getByRole("status")).toHaveClass("my-empty");
  });
});
