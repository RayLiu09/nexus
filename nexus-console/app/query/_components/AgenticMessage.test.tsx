/**
 * B4c smoke tests — AgenticMessage renders timeline + right panel
 * correctly, and clicking a step swaps the right panel from "final
 * markdown" to "step detail".
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AgenticMessage } from "./AgenticMessage";
import type { AgenticTurnState } from "./AgenticMessage";
import type { StepPayload } from "../_lib/queryTypes";

vi.mock("./EchartsFence", () => ({
  EchartsFence: ({ raw }: { raw: string }) => <div data-testid="echarts-fence-stub">{raw}</div>,
}));

function makeStep(
  id: StepPayload["id"],
  label: string,
  status: StepPayload["status"] = "completed",
  overrides: Partial<StepPayload> = {},
): StepPayload {
  return {
    id,
    label,
    status,
    input: { seeded: "in" },
    output: status === "running" ? null : { seeded: "out" },
    started_at_ms: 1000,
    completed_at_ms: status === "running" ? 0 : 1050,
    error: null,
    ...overrides,
  };
}

function makeTurn(overrides: Partial<AgenticTurnState> = {}): AgenticTurnState {
  return {
    query: "跨境电商 2025 政策",
    createdAt: new Date("2026-07-20T09:00:00Z"),
    steps: [
      makeStep("intent_classify", "意图分类"),
      makeStep("param_extract", "参数抽取"),
      makeStep("dispatch", "工具调度"),
      makeStep("compose", "Markdown 汇总"),
    ],
    markdown: "# 结果\n\n段落内容",
    intent: "scenario_1",
    intentConfidence: 0.95,
    invokedTools: ["internal.search_chunks_by_semantic"],
    fallbackReason: null,
    warnings: [],
    templateId: null,
    isStreaming: false,
    error: null,
    ...overrides,
  };
}

describe("AgenticMessage", () => {
  it("renders user question, meta tags, and final markdown by default", () => {
    render(<AgenticMessage turn={makeTurn()} />);
    expect(screen.getByText("跨境电商 2025 政策")).toBeInTheDocument();
    expect(screen.getByTestId("query-meta-intent")).toHaveTextContent("scenario_1");
    expect(screen.getByTestId("query-meta-tools")).toHaveTextContent("工具 · 1");
    // Default right pane = final markdown.
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("结果");
    expect(screen.getByText("段落内容")).toBeInTheDocument();
  });

  it("renders every step in the vertical timeline", () => {
    render(<AgenticMessage turn={makeTurn()} />);
    expect(screen.getByTestId("query-step-intent_classify")).toBeInTheDocument();
    expect(screen.getByTestId("query-step-param_extract")).toBeInTheDocument();
    expect(screen.getByTestId("query-step-dispatch")).toBeInTheDocument();
    expect(screen.getByTestId("query-step-compose")).toBeInTheDocument();
    // "最终回答" pseudo-step is present for quick return to markdown view.
    expect(screen.getByTestId("query-step-final")).toBeInTheDocument();
  });

  it("clicking a step swaps the right pane to StepDetailPanel", async () => {
    const user = userEvent.setup();
    render(<AgenticMessage turn={makeTurn()} />);
    // Right pane before click — final markdown visible.
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("结果");
    // Click dispatch step.
    await user.click(screen.getByTestId("query-step-dispatch"));
    // Step detail viewer shows input/output.
    expect(screen.getByText("输入")).toBeInTheDocument();
    expect(screen.getByText("输出")).toBeInTheDocument();
    // JSON block contains the seeded input/output value.
    expect(screen.getByText(/"seeded": "in"/)).toBeInTheDocument();
    expect(screen.getByText(/"seeded": "out"/)).toBeInTheDocument();
    // Markdown h1 no longer in the right pane.
    expect(screen.queryByRole("heading", { level: 1, name: "结果" })).not.toBeInTheDocument();
    // Clicking "最终回答" returns to markdown view.
    await user.click(screen.getByTestId("query-step-final"));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("结果");
  });

  it("shows a placeholder for a running step's empty output", async () => {
    const user = userEvent.setup();
    render(
      <AgenticMessage
        turn={makeTurn({
          steps: [makeStep("intent_classify", "意图分类", "running")],
          markdown: "",
          isStreaming: true,
        })}
      />,
    );
    await user.click(screen.getByTestId("query-step-intent_classify"));
    expect(screen.getByText(/步骤执行中/)).toBeInTheDocument();
  });

  it("renders the streaming hint when isStreaming with partial markdown", () => {
    render(
      <AgenticMessage
        turn={makeTurn({
          isStreaming: true,
          markdown: "# 生成中",
        })}
      />,
    );
    expect(screen.getByTestId("query-streaming-hint")).toBeInTheDocument();
  });

  it("shows fallback tag when fallback_reason is set", () => {
    render(<AgenticMessage turn={makeTurn({ fallbackReason: "unknown_fallback" })} />);
    expect(screen.getByTestId("query-meta-fallback")).toHaveTextContent("兜底检索");
  });
});
