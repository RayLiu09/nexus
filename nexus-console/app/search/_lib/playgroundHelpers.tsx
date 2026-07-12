"use client";

import { Space, Tag, Typography } from "antd";
import type { ReactNode } from "react";

import type { RetrievalConversationStep } from "@/lib/retrievalTypes";

export function createId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    idle: "就绪",
    pending: "等待",
    running: "执行中",
    completed: "完成",
    needs_clarification: "需澄清",
    blocked: "阻断",
    failed: "失败",
    skipped: "跳过",
    planned: "已规划",
    partial: "部分完成",
  };
  return labels[status] ?? status;
}

export function statusColor(status: string): string {
  const colors: Record<string, string> = {
    idle: "default",
    pending: "default",
    running: "processing",
    completed: "success",
    needs_clarification: "warning",
    blocked: "warning",
    failed: "error",
    skipped: "default",
    planned: "processing",
    partial: "warning",
  };
  return colors[status] ?? "default";
}

export function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function formatTime(value: Date): string {
  return value.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/**
 * Playground-local JSON viewer. Kept separate from the shared
 * `components/retrieval/JsonPreview` (which sports a copy button) so the
 * conversation UI stays visually calm — a `<pre>` block is enough here.
 */
export function InlineJsonPreview({
  value,
  maxHeight = "max-h-56",
}: {
  value: unknown;
  maxHeight?: string;
}) {
  return (
    <pre
      className={`${maxHeight} overflow-auto rounded bg-white p-3 text-xs text-[var(--text-secondary)]`}
    >
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function MetricBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--surface-alt)] p-3">
      <Typography.Text type="secondary" className="block text-xs">
        {label}
      </Typography.Text>
      <Typography.Text strong>{value}</Typography.Text>
    </div>
  );
}

export function ResultSectionTitle({ title, tags }: { title: string; tags: Array<string | null> }) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <Typography.Text strong>{title}</Typography.Text>
      {tags
        .filter((tag): tag is string => Boolean(tag))
        .map((tag) => (
          <Tag key={tag}>{tag}</Tag>
        ))}
    </div>
  );
}

export function CollapseLabel({ icon, text }: { icon: ReactNode; text: string }) {
  return (
    <Space>
      {icon}
      <span>{text}</span>
    </Space>
  );
}

/**
 * Simulated retrieval steps used while the assistant message is still
 * running (before the backend fills in `conversation_steps`). The `tick`
 * counter — driven by a 900ms interval in SearchPlayground — advances
 * `activeIndex` every two ticks so the UI animates predictably.
 */
export function buildLiveRetrievalSteps(tick: number): RetrievalConversationStep[] {
  const activeIndex = Math.min(Math.floor(tick / 2), 4);
  const base = [
    ["intent_recognition", "意图识别", "理解用户问题并映射到平台数据领域"],
    ["query_transformation", "问题转化", "生成可执行的结构化/非结构化召回计划"],
    ["parallel_retrieval", "并行检索", "按召回计划执行各子查询"],
    ["context_assembly", "上下文组装", "合并检索片段、结构化记录和来源定位"],
    ["summary_generation", "结果生成", "生成可追溯的 Markdown 结构化结果"],
  ] as const;
  return base.map(([step, title, message], index) => ({
    step,
    title,
    message,
    display_to_user: true,
    status: index < activeIndex ? "completed" : index === activeIndex ? "running" : "pending",
    progress: index === activeIndex ? { elapsed_ticks: tick } : undefined,
  }));
}

export function buildLegacySteps(
  mode: "search" | "qa",
  activeIndex: number,
  count?: number,
): RetrievalConversationStep[] {
  const base =
    mode === "search"
      ? [
          ["query_parse", "查询解析", "读取检索参数"],
          ["semantic_search", "语义检索", "调用语义检索接口"],
          ["citation_render", "引用呈现", "展示命中 chunk 与定位"],
        ]
      : [
          ["question_parse", "问题解析", "读取问答参数"],
          ["qa_request", "问答执行", "调用 QA 接口生成回答"],
          ["source_render", "来源呈现", "展示引用源"],
        ];
  return base.map(([step, title, message], index) => ({
    step,
    title,
    message: count != null && index === base.length - 1 ? `${message}，返回 ${count} 条` : message,
    display_to_user: true,
    status: index < activeIndex ? "completed" : index === activeIndex ? "running" : "pending",
  }));
}
