/**
 * B8 tests — QueryRouterAnswer markdown renderer.
 *
 * ECharts requires a Canvas backend so the graph render itself is
 * hard to exercise in jsdom (would need canvas-mock). We instead
 * verify the *dispatch*: the renderer must hit EchartsFence for
 * chart:echarts fences (and swallow parse failures gracefully) and
 * must style generated blockquotes distinctly for the reader.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { QueryRouterAnswer } from "./QueryRouterAnswer";

vi.mock("./EchartsFence", () => ({
  EchartsFence: ({ raw }: { raw: string }) => <div data-testid="echarts-fence-stub">{raw}</div>,
}));

describe("QueryRouterAnswer", () => {
  it("renders standard markdown headings and paragraphs", () => {
    render(<QueryRouterAnswer markdown={"# 标题\n\n这是段落"} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("标题");
    expect(screen.getByText("这是段落")).toBeInTheDocument();
  });

  it("dispatches chart:echarts fences to EchartsFence with raw JSON", () => {
    const chartJson = '{"type":"graph","nodes":[],"edges":[]}';
    const markdown = ["前置文本", "", "```chart:echarts", chartJson, "```", "", "后置文本"].join(
      "\n",
    );
    render(<QueryRouterAnswer markdown={markdown} />);
    const stub = screen.getByTestId("echarts-fence-stub");
    expect(stub).toHaveTextContent(chartJson);
    expect(screen.getByText("前置文本")).toBeInTheDocument();
    expect(screen.getByText("后置文本")).toBeInTheDocument();
  });

  it("renders non-chart fenced code as plain <pre>", () => {
    const markdown = ["```json", '{"a": 1}', "```"].join("\n");
    render(<QueryRouterAnswer markdown={markdown} />);
    expect(screen.queryByTestId("echarts-fence-stub")).not.toBeInTheDocument();
    // <pre> gets the code content — assert on the content, not the tag.
    expect(screen.getByText(/"a": 1/)).toBeInTheDocument();
  });

  it("styles blockquotes with ⚠️ marker as generated content", () => {
    const markdown = "> ⚠️ 以下为模型推断内容\n> 此段无平台资产支撑";
    render(<QueryRouterAnswer markdown={markdown} />);
    const block = screen.getByTestId("query-generated-block");
    expect(block).toBeInTheDocument();
    expect(block).toHaveAttribute("aria-label", "模型推断内容");
  });

  it("leaves ordinary blockquotes untouched", () => {
    const markdown = "> 普通引用段落，非模型推断";
    render(<QueryRouterAnswer markdown={markdown} />);
    expect(screen.queryByTestId("query-generated-block")).not.toBeInTheDocument();
    expect(screen.getByText(/普通引用段落/)).toBeInTheDocument();
  });

  it("renders footnote references via remark-gfm", () => {
    const markdown = "参考本条政策[^ref1]。\n\n[^ref1]: 政策原文来源";
    const { container } = render(<QueryRouterAnswer markdown={markdown} />);
    // remark-gfm emits <sup> footnote refs with a link inside.
    const supLink = container.querySelector("sup a");
    expect(supLink).not.toBeNull();
    const footnotes = screen.getByTestId("query-footnotes");
    expect(footnotes).not.toHaveAttribute("open");
    expect(screen.getByText("来源引用")).toBeInTheDocument();
    // The footnote definition remains in the collapsed source section.
    expect(screen.getByText(/政策原文来源/)).toBeInTheDocument();
  });
});
