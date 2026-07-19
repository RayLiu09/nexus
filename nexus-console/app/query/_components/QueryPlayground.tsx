"use client";

/**
 * B8 (§10 Batch B3b) — Query Router v2 playground shell.
 *
 * Left column: composer (Antd TextArea + submit). Right column: the
 * assistant response rendered via `QueryRouterAnswer` plus a compact
 * meta strip showing intent / confidence / invoked tools / fallback
 * reason (§8.2 audit fields surfaced to the user for transparency).
 *
 * State model — deliberately local `useState` for now: single query,
 * single response, no history. When the design settles on a
 * conversational history UI (paralleling /search's playground) we
 * can lift into TanStack Query for cache + retry.
 */
import { Alert, Button, Input, Space, Tag } from "antd";
import { useState } from "react";

import { QueryRouterAnswer } from "./QueryRouterAnswer";
import { fetchQueryRouterAnswer } from "../_lib/fetchers";
import type { QueryRouterResponse } from "../_lib/queryTypes";

const MAX_QUERY_LENGTH = 2048;

type Status = "idle" | "running" | "success" | "error";

export function QueryPlayground() {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [result, setResult] = useState<QueryRouterResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isRunning = status === "running";
  const isEmpty = query.trim().length === 0;
  const isTooLong = query.length > MAX_QUERY_LENGTH;
  const canSubmit = !isRunning && !isEmpty && !isTooLong;

  async function handleSubmit(): Promise<void> {
    if (!canSubmit) return;
    setStatus("running");
    setError(null);
    try {
      const data = await fetchQueryRouterAnswer(query.trim());
      setResult(data);
      setStatus("success");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "请求失败");
      setStatus("error");
    }
  }

  function handleReset(): void {
    setQuery("");
    setResult(null);
    setError(null);
    setStatus("idle");
  }

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
        {status === "idle" && !result && <IdleHint />}
        {status === "error" && (
          <Alert
            type="error"
            title="查询失败"
            description={error ?? "请稍后重试"}
            action={
              <Button size="small" onClick={handleSubmit}>
                重试
              </Button>
            }
            showIcon
          />
        )}
        {result && <QueryResultView result={result} />}
      </section>
    </div>
  );
}

interface QueryResultViewProps {
  result: QueryRouterResponse;
}

function QueryResultView({ result }: QueryResultViewProps) {
  return (
    <div className="border-line bg-surface rounded-lg border p-4">
      <QueryMetaStrip result={result} />
      <div className="border-line mt-3 border-t pt-3">
        <QueryRouterAnswer markdown={result.markdown} />
      </div>
    </div>
  );
}

function QueryMetaStrip({ result }: QueryResultViewProps) {
  const { intent, intent_confidence, invoked_tools, fallback_reason } = result;
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-gray-600">
      <Tag color="blue" data-testid="query-meta-intent">
        意图 · {intent}
      </Tag>
      <Tag variant="filled">置信度 {intent_confidence.toFixed(2)}</Tag>
      {invoked_tools.length > 0 && (
        <Tag color="geekblue" data-testid="query-meta-tools">
          工具 · {invoked_tools.length}
        </Tag>
      )}
      {fallback_reason && (
        <Tag color="orange" data-testid="query-meta-fallback">
          {formatFallback(fallback_reason)}
        </Tag>
      )}
    </div>
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
