import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PageHeader } from "@/components/PageHeader";

describe("PageHeader", () => {
  it("renders h1 title", () => {
    render(<PageHeader title="资产目录" />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("资产目录");
  });

  it("renders eyebrow badge", () => {
    render(<PageHeader eyebrow="数据接入" title="原始台账" />);
    expect(screen.getByText("数据接入")).toBeInTheDocument();
  });

  it("falls back to prototypeId for eyebrow", () => {
    render(<PageHeader prototypeId="NX-01" title="工作台" />);
    expect(screen.getByText("NX-01")).toBeInTheDocument();
  });

  it("renders description", () => {
    render(<PageHeader title="标题" description="这是描述文字" />);
    expect(screen.getByText("这是描述文字")).toBeInTheDocument();
  });

  it("renders actions", () => {
    render(<PageHeader title="标题" actions={<button type="button">新建</button>} />);
    expect(screen.getByRole("button", { name: "新建" })).toBeInTheDocument();
  });

  it("does not render badge when no eyebrow or prototypeId", () => {
    const { container } = render(<PageHeader title="仅标题" />);
    expect(container.querySelector(".page-header-badge")).not.toBeInTheDocument();
  });
});
