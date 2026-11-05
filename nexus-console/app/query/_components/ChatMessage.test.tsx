import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ChatMessage } from "./ChatMessage";
import type { AgenticTurnState } from "./AgenticMessage";

vi.mock("./EchartsFence", () => ({ EchartsFence: () => null }));

const turn: AgenticTurnState = {
  query: "专业布点统计",
  createdAt: new Date(),
  intent: "public_tools",
  intentConfidence: null,
  markdown: "实际统计结果 [1]",
  steps: [],
  invokedTools: [],
  fallbackReason: null,
  warnings: [],
  templateId: null,
  isStreaming: false,
  error: null,
  citations: [
    {
      citation_id: "1",
      source_type: "aggregate",
      title: "重庆专业布点",
      excerpt: "已入库的院校数为3",
      tool: "aggregate_major_offerings",
      scope: { province: "重庆" },
    },
  ],
};

describe("ChatMessage sources", () => {
  it("shows per-call counts and query conditions without attributing cumulative sources to an empty action", () => {
    const base = {
      status: "completed" as const,
      started_at_ms: 1,
      completed_at_ms: 2,
      error: null,
      label: "查找资产文档",
      tool_name: "find_documents",
    };
    render(
      <ChatMessage
        turn={{
          ...turn,
          isStreaming: true,
          steps: [
            {
              ...base,
              id: "docs-policy",
              input: { query_summary: "资料类型：产业政策；地区：重庆" },
              output: {
                outcome: "success",
                source_count: 2,
                new_source_count: 1,
                total_source_count: 37,
              },
            },
            {
              ...base,
              id: "docs-chain",
              input: { query_summary: "关键词：产业链" },
              output: {
                outcome: "empty",
                source_count: 0,
                new_source_count: 0,
                total_source_count: 37,
              },
            },
            {
              ...base,
              id: "docs-legacy",
              input: {},
              output: { outcome: "empty", source_count: 37 },
            },
          ],
        }}
      />,
    );
    expect(screen.getByText("查找资产文档 · 资料类型：产业政策；地区：重庆")).toBeInTheDocument();
    expect(screen.getByText("查找资产文档 · 关键词：产业链")).toBeInTheDocument();
    expect(screen.getByText("本次取得 2 条候选资料，其中新增 1 条")).toBeInTheDocument();
    expect(screen.getAllByText("未找到匹配内容")).toHaveLength(2);
    expect(document.body.textContent).not.toContain("37");
  });

  it("collapses source cards initially and hides technical identifiers in source details", async () => {
    const id = "12345678-1234-4321-9876-123456789abc";
    render(
      <ChatMessage
        turn={{
          ...turn,
          citations: [
            {
              ...turn.citations![0],
              title: "重庆专业布点-abcdef123456.html",
              record_id: id,
              normalized_ref_id: id,
              excerpt: JSON.stringify({
                id,
                record_id: id,
                school_count: 3,
                major_name: "电子商务",
                api_key: "private-key",
              }),
              scope: { province_name: "重庆市", normalized_ref_ids: [id], top_k: 8 },
            },
          ],
        }}
      />,
    );
    const sources = screen.getByLabelText("引用来源");
    expect(sources).not.toHaveAttribute("open");
    await userEvent.click(screen.getByText("引用来源 · 1"));
    expect(sources).toHaveAttribute("open");
    await userEvent.click(screen.getByRole("link", { name: "1" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("省份：重庆市")).toBeInTheDocument();
    expect(screen.getAllByText(/院校数：3/).length).toBeGreaterThan(0);
    expect(document.body.textContent).not.toContain(id);
    expect(document.body.textContent).not.toContain("abcdef123456");
    expect(document.body.textContent).not.toContain("record_id");
    expect(document.body.textContent).not.toContain("api_key");
    expect(document.body.textContent).not.toContain("private-key");
  });

  it("opens the matching actual source from an inline citation", async () => {
    render(<ChatMessage turn={turn} />);
    await userEvent.click(screen.getByRole("link", { name: "1" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("引用 [1] · 重庆专业布点")).toBeInTheDocument();
    expect(screen.getAllByText("已入库的院校数为3").length).toBeGreaterThan(0);
  });

  it("shows only actually cited sources even while candidate metadata is streaming", () => {
    render(<ChatMessage turn={{ ...turn, isStreaming: true, citations: [
      ...turn.citations!, { ...turn.citations![0], citation_id: "2", title: "尚未使用的资料" },
    ] }} />);
    expect(screen.getByText("引用来源 · 1")).toBeInTheDocument();
    expect(screen.queryByText("尚未使用的资料")).not.toBeInTheDocument();
  });

  it("labels external results and never renders unsafe source URLs", async () => {
    render(
      <ChatMessage
        turn={{
          ...turn,
          citations: [
            { ...turn.citations![0], source_type: "external_web", url: "javascript:alert(1)" },
          ],
        }}
      />,
    );
    await userEvent.click(screen.getByRole("link", { name: "1" }));
    expect(
      await screen.findByText("该引用来自公开网页，不代表已通过平台资产治理。"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "打开网络资源" })).not.toBeInTheDocument();
  });

  it("keeps external resource access without a platform asset link", async () => {
    render(<ChatMessage turn={{ ...turn, citations: [{
      ...turn.citations![0], source_type: "external_web",
      asset_id: "asset-anchor", url: "https://example.com/policy",
    }] }} />);
    await userEvent.click(screen.getByRole("link", { name: "1" }));
    const link = await screen.findByRole("link", { name: "打开网络资源" });
    expect(link).toHaveAttribute("href", "https://example.com/policy");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.queryByRole("link", { name: "查看平台资产" })).not.toBeInTheDocument();
    expect(document.querySelector('a[href^="/assets/"]')).toBeNull();
  });

  it.each(["query_market_jobs", "get_market_job"])("omits network resource access for a job citation from %s", async (tool) => {
    render(<ChatMessage turn={{ ...turn, citations: [{
      ...turn.citations![0], source_type: "record", tool,
      title: "数据分析师", excerpt: "负责业务数据分析与报表建设。",
      url: "https://example.com/jobs/data-analyst",
    }] }} />);
    await userEvent.click(screen.getByRole("link", { name: "1" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("引用 [1] · 数据分析师")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "打开网络资源" })).not.toBeInTheDocument();
    expect(document.querySelector('a[href="https://example.com/jobs/data-analyst"]')).toBeNull();
  });
});
