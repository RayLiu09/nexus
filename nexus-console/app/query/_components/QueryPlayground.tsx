"use client";

/**
 * B8 (§10 Batch B3b + SSE) — Query Router v2 playground shell.
 *
 * Left column: composer (Antd TextArea + submit). Right column:
 * streaming assistant response.  During the stream we render the
 * accumulated raw markdown (chart placeholders visible verbatim per
 * §7.3); when the ``final`` frame arrives we swap to the fully-
 * replaced markdown and unlock the composer.
 */
import { Alert, Button, Input, Space, Tag } from "antd";
import { useCallback, useMemo, useState } from "react";

import { QueryRouterAnswer } from "./QueryRouterAnswer";
import { useQueryRouterStream } from "../_lib/useQueryRouterStream";
import type { UseQueryRouterStreamState } from "../_lib/useQueryRouterStream";

const MAX_QUERY_LENGTH = 2048;

export function QueryPlayground() {
  const [query, setQuery] = useState("");
  const { state, start, reset } = useQueryRouterStream();

  const isRunning = state.status === "running";
  const isEmpty = query.trim().length === 0;
  const isTooLong = query.length > MAX_QUERY_LENGTH;
  const canSubmit = !isRunning && !isEmpty && !isTooLong;

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return;
    await start(query.trim());
  }, [canSubmit, query, start]);

  const handleReset = useCallback(() => {
    setQuery("");
    reset();
  }, [reset]);

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,340px)_1fr]">
      <section aria-label="查询输入区" className="border-line bg-surface rounded-lg border p-4">
        <Space orientation="vertical" size="middle" style={{ display: "flex" }}>
          <Input.TextArea
            data-testid="query-composer-input"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="例如：跨境电商专业 2025 年岗位需求分布如何？"
            autoSize={{ minRows: 5, maxRows: 12 }}
            maxLength={MAX_QUERY_LENGTH}
            showCount
            disabled={isRunning}
          />
          <div className="flex items-center justify-end gap-2">
            <Button onClick={handleReset} disabled={isRunning}>
              清空
            </Button>
            <Button
              type="primary"
              onClick={handleSubmit}
              loading={isRunning}
              disabled={!canSubmit}
              data-testid="query-composer-submit"
            >
              提交查询
            </Button>
          </div>
        </Space>
      </section>

      <section aria-label="查询结果区" className="min-h-[240px]">
        <QueryResultPanel state={state} onRetry={handleSubmit} />
      </section>
    </div>
  );
}

interface QueryResultPanelProps {
  state: UseQueryRouterStreamState;
  onRetry: () => void;
}

function QueryResultPanel({ state, onRetry }: QueryResultPanelProps) {
  if (state.status === "idle" && !state.result && !state.rawMarkdown) {
    return <IdleHint />;
  }

  if (state.status === "error" && !state.result) {
    return (
      <Alert
        type="error"
        title="查询失败"
        description={state.error ?? "请稍后重试"}
        action={
          <Button size="small" onClick={onRetry}>
            重试
          </Button>
        }
        showIcon
      />
    );
  }

  // Final markdown (chart placeholders swapped) takes priority; while
  // streaming we render `rawMarkdown` so the user sees progress.
  const markdown = state.result?.markdown ?? state.rawMarkdown;
  return (
    <div className="border-line bg-surface rounded-lg border p-4">
      <QueryMetaStrip state={state} />
      <div className="border-line mt-3 border-t pt-3">
        <QueryRouterAnswer markdown={markdown} />
        {state.status === "running" && !state.result && <StreamingHint />}
      </div>
    </div>
  );
}

function QueryMetaStrip({ state }: { state: UseQueryRouterStreamState }) {
  const meta = state.meta;
  const result = state.result;

  const intent = result?.intent ?? meta?.intent;
  const confidence = result?.intent_confidence ?? meta?.intent_confidence;
  const invokedTools = result?.invoked_tools ?? meta?.invoked_tools ?? [];
  const fallbackReason = result?.fallback_reason ?? meta?.fallback_reason;

  const confidenceLabel = useMemo(() => {
    if (typeof confidence !== "number") return null;
    return confidence.toFixed(2);
  }, [confidence]);

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-gray-600">
      {intent && (
        <Tag color="blue" data-testid="query-meta-intent">
          意图 · {intent}
        </Tag>
      )}
      {confidenceLabel && <Tag variant="filled">置信度 {confidenceLabel}</Tag>}
      {invokedTools.length > 0 && (
        <Tag color="geekblue" data-testid="query-meta-tools">
          工具 · {invokedTools.length}
        </Tag>
      )}
      {fallbackReason && (
        <Tag color="orange" data-testid="query-meta-fallback">
          {formatFallback(fallbackReason)}
        </Tag>
      )}
      {state.status === "running" && <Tag color="processing">流式生成中…</Tag>}
    </div>
  );
}

function StreamingHint() {
  return (
    <p className="mt-3 text-xs text-gray-400" data-testid="query-streaming-hint">
      正在流式接收模型输出，图表将在完成后统一渲染…
    </p>
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

function IdleHint() {
  return (
    <div className="border-line rounded-lg border border-dashed bg-white/60 p-6 text-center text-sm text-gray-500">
      在左侧输入你的检索问题，系统将自动识别意图、执行结构化 / 语义检索并生成 Markdown 汇总。
    </div>
  );
}
