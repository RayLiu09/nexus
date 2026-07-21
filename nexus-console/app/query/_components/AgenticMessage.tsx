"use client";

/**
 * B4c — one assistant turn.
 *
 * Layout (desktop):
 *   ┌─────────────────────────────────────────────────────────────┐
 *   │  User bubble (top-right, blue)                             │
 *   ├─────────────────────────────────────────────────────────────┤
 *   │  Assistant card                                             │
 *   │  ┌───────────────────┬──────────────────────────────────┐   │
 *   │  │ Agentic timeline  │  RightPanel:                     │   │
 *   │  │ (~280px, vertical)│    - Step selected → StepDetail  │   │
 *   │  │                   │    - No selection → QueryRouter- │   │
 *   │  │                   │      Answer (final markdown)     │   │
 *   │  └───────────────────┴──────────────────────────────────┘   │
 *   │  Meta strip (intent / confidence / tools / fallback)        │
 *   └─────────────────────────────────────────────────────────────┘
 *
 * Works for both the streaming turn (state comes from
 * ``useQueryRouterStream``) and frozen historical turns (state
 * snapshotted at completion time).  The prop shape is identical so
 * the same component renders both.
 */
import { Alert, Tag } from "antd";
import { useState } from "react";

import { ChunkPreviewDrawer } from "@/components/chunk/ChunkPreviewDrawer";
import type { KnowledgeChunkHit } from "@/lib/chunkTypes";

import { AgenticStepTimeline } from "./AgenticStepTimeline";
import { QueryRouterAnswer } from "./QueryRouterAnswer";
import { StepDetailPanel } from "./StepDetailPanel";
import type { StepPayload } from "../_lib/queryTypes";

export interface AgenticTurnState {
  query: string;
  createdAt: Date;
  steps: StepPayload[];
  markdown: string;
  intent: string | null;
  intentConfidence: number | null;
  invokedTools: string[];
  fallbackReason: string | null;
  warnings: string[];
  templateId: string | null;
  isStreaming: boolean;
  error: string | null;
}

interface AgenticMessageProps {
  turn: AgenticTurnState;
}

export function AgenticMessage({ turn }: AgenticMessageProps) {
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [selectedChunk, setSelectedChunk] = useState<KnowledgeChunkHit | null>(null);
  const selectedStep = selectedStepId
    ? (turn.steps.find((s) => s.id === selectedStepId) ?? null)
    : null;

  return (
    <article className="space-y-3" data-testid="query-turn">
      <UserBubble query={turn.query} createdAt={turn.createdAt} />
      <div className="border-line bg-surface rounded-lg border p-4">
        <TurnMetaStrip turn={turn} />
        <div className="mt-3 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,280px)_1fr]">
          <aside aria-label="执行步骤时间线">
            <AgenticStepTimeline
              steps={turn.steps}
              selectedStepId={selectedStepId}
              onSelect={setSelectedStepId}
            />
          </aside>
          <section
            aria-label={selectedStep ? "步骤执行详情" : "最终回答"}
            className="border-line min-h-[240px] rounded-md border bg-white p-3"
          >
            {selectedStep ? (
              <StepDetailPanel step={selectedStep} onSelectChunk={setSelectedChunk} />
            ) : (
              <FinalAnswerPanel turn={turn} onSelectChunk={setSelectedChunk} />
            )}
          </section>
        </div>
      </div>
      <ChunkPreviewDrawer
        chunk={selectedChunk}
        open={selectedChunk !== null}
        onClose={() => setSelectedChunk(null)}
      />
    </article>
  );
}

interface UserBubbleProps {
  query: string;
  createdAt: Date;
}

function UserBubble({ query, createdAt }: UserBubbleProps) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-lg bg-blue-600 px-4 py-2 text-sm text-white shadow-sm">
        <p className="whitespace-pre-wrap">{query}</p>
        <p className="mt-1 text-right text-[10px] text-blue-100/80">
          {createdAt.toLocaleTimeString("zh-CN", { hour12: false })}
        </p>
      </div>
    </div>
  );
}

interface TurnMetaStripProps {
  turn: AgenticTurnState;
}

function TurnMetaStrip({ turn }: TurnMetaStripProps) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-gray-600">
      {turn.intent && (
        <Tag color="blue" data-testid="query-meta-intent">
          意图 · {turn.intent}
        </Tag>
      )}
      {turn.intentConfidence !== null && (
        <Tag variant="filled">置信度 {turn.intentConfidence.toFixed(2)}</Tag>
      )}
      {turn.invokedTools.length > 0 && (
        <Tag color="geekblue" data-testid="query-meta-tools">
          工具 · {turn.invokedTools.length}
        </Tag>
      )}
      {turn.templateId && (
        <Tag color="purple" data-testid="query-meta-template">
          模板 · {turn.templateId}
        </Tag>
      )}
      {turn.fallbackReason && (
        <Tag color="orange" data-testid="query-meta-fallback">
          {formatFallback(turn.fallbackReason)}
        </Tag>
      )}
      {turn.isStreaming && <Tag color="processing">流式生成中…</Tag>}
    </div>
  );
}

interface FinalAnswerPanelProps {
  turn: AgenticTurnState;
  onSelectChunk: (chunk: KnowledgeChunkHit) => void;
}

function FinalAnswerPanel({ turn, onSelectChunk }: FinalAnswerPanelProps) {
  if (turn.error && !turn.markdown) {
    return <Alert type="error" title="查询失败" description={turn.error} showIcon />;
  }
  if (!turn.markdown) {
    return (
      <p className="text-sm text-gray-400">
        {turn.isStreaming
          ? "正在流式接收模型输出，图表将在完成后统一渲染…"
          : "暂无回答内容，请查看左侧步骤诊断。"}
      </p>
    );
  }
  return (
    <>
      <QueryRouterAnswer markdown={turn.markdown} onSelectChunk={onSelectChunk} />
      {turn.isStreaming && (
        <p className="mt-3 text-xs text-gray-400" data-testid="query-streaming-hint">
          正在流式接收模型输出，图表将在完成后统一渲染…
        </p>
      )}
    </>
  );
}

function formatFallback(reason: string): string {
  switch (reason) {
    case "unknown_fallback":
      return "兜底检索";
    case "scenario_5_template_not_implemented":
      return "培养方案模板 P0 未实现";
    default:
      return reason;
  }
}
