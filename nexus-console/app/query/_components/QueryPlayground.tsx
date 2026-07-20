"use client";

/**
 * B4c — Query Router v2 conversation playground.
 *
 * Chat-style shell holding an in-memory conversation history (loses
 * on refresh — per B4 scope):
 *   ┌─────────────────────────────────────────────────────────────┐
 *   │  <history stack of AgenticMessage components, oldest top>   │
 *   │  <active streaming turn — same component, isStreaming=true> │
 *   ├─────────────────────────────────────────────────────────────┤
 *   │  Composer (bottom, sticky)                                  │
 *   └─────────────────────────────────────────────────────────────┘
 *
 * State model:
 *   - ``history: FrozenTurn[]`` — completed turns, snapshotted from
 *     the stream hook at ``done`` time.
 *   - ``activeQuery: string | null`` — the query currently in flight;
 *     the SSE stream hook drives its live state.
 *   - When streaming completes we snapshot hook state into a new
 *     frozen turn, append to history, reset the hook, clear
 *     activeQuery.
 *
 * The refresh path skips remounting the stream hook when the user
 * only opens a step's detail panel — we lift ``useQueryRouterStream``
 * to the playground level so click-through interactions don't cancel
 * an in-flight request.
 */
import { Alert, Button, Input, Space } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";

import { AgenticMessage } from "./AgenticMessage";
import type { AgenticTurnState } from "./AgenticMessage";
import { useQueryRouterStream } from "../_lib/useQueryRouterStream";
import type { UseQueryRouterStreamState } from "../_lib/useQueryRouterStream";

const MAX_QUERY_LENGTH = 2048;

export function QueryPlayground() {
  const [query, setQuery] = useState("");
  const [history, setHistory] = useState<AgenticTurnState[]>([]);
  const [activeQuery, setActiveQuery] = useState<string | null>(null);
  const [activeCreatedAt, setActiveCreatedAt] = useState<Date | null>(null);
  const { state, start, reset } = useQueryRouterStream();
  const feedRef = useRef<HTMLDivElement | null>(null);
  const snapshottedRef = useRef<string | null>(null);

  const isRunning = state.status === "running";
  const isEmpty = query.trim().length === 0;
  const isTooLong = query.length > MAX_QUERY_LENGTH;
  const canSubmit = !isRunning && !isEmpty && !isTooLong && activeQuery === null;

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return;
    const submittedQuery = query.trim();
    setQuery("");
    setActiveQuery(submittedQuery);
    setActiveCreatedAt(new Date());
    snapshottedRef.current = null;
    await start(submittedQuery);
  }, [canSubmit, query, start]);

  const handleReset = useCallback(() => {
    setQuery("");
    reset();
    setActiveQuery(null);
    setActiveCreatedAt(null);
    setHistory([]);
    snapshottedRef.current = null;
  }, [reset]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key !== "Enter") return;
      // Skip while an IME composition is open — otherwise pressing
      // Enter to confirm a Chinese/Japanese candidate would submit
      // instead of committing the character.  `isComposing` is on the
      // native event; React 19 also exposes `event.nativeEvent`.
      if ((event.nativeEvent as KeyboardEvent).isComposing) return;
      // Ctrl/Cmd + Enter OR Shift + Enter → newline (default
      // textarea behaviour; don't preventDefault).
      if (event.ctrlKey || event.metaKey || event.shiftKey) return;
      // Plain Enter → submit.
      event.preventDefault();
      void handleSubmit();
    },
    [handleSubmit],
  );

  // When streaming completes (success or error), freeze the hook's
  // state into a new turn, append to history, reset the hook. The
  // ref guard prevents double-appending if the hook state settles
  // across multiple renders.
  useEffect(() => {
    if (!activeQuery || activeCreatedAt === null) return;
    if (state.status !== "success" && state.status !== "error") return;
    if (snapshottedRef.current === activeQuery) return;
    snapshottedRef.current = activeQuery;
    const frozen = snapshotTurn(activeQuery, activeCreatedAt, state, false);
    setHistory((prev) => [...prev, frozen]);
    setActiveQuery(null);
    setActiveCreatedAt(null);
    reset();
  }, [activeQuery, activeCreatedAt, state, reset]);

  // Auto-scroll to the bottom whenever history grows OR chunks stream in.
  useEffect(() => {
    const el = feedRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [history.length, state.rawMarkdown, state.result, state.steps.length]);

  const activeTurn: AgenticTurnState | null =
    activeQuery && activeCreatedAt !== null
      ? snapshotTurn(activeQuery, activeCreatedAt, state, true)
      : null;

  return (
    <div className="flex h-[calc(100vh-220px)] flex-col gap-4">
      <div
        ref={feedRef}
        className="border-line flex-1 space-y-6 overflow-y-auto rounded-lg border bg-gray-50/60 p-4"
        role="log"
        aria-live="polite"
      >
        {history.length === 0 && !activeTurn && <IdleHint />}
        {history.map((turn, idx) => (
          <AgenticMessage key={`${turn.createdAt.getTime()}-${idx}`} turn={turn} />
        ))}
        {activeTurn && <AgenticMessage key="active" turn={activeTurn} />}
      </div>
      <ComposerBar
        query={query}
        onChange={setQuery}
        onKeyDown={handleKeyDown}
        onSubmit={handleSubmit}
        onReset={handleReset}
        canSubmit={canSubmit}
        isRunning={isRunning}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Composer bar
// ---------------------------------------------------------------------------

interface ComposerBarProps {
  query: string;
  onChange: (value: string) => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onSubmit: () => void;
  onReset: () => void;
  canSubmit: boolean;
  isRunning: boolean;
}

function ComposerBar({
  query,
  onChange,
  onKeyDown,
  onSubmit,
  onReset,
  canSubmit,
  isRunning,
}: ComposerBarProps) {
  return (
    <div className="border-line bg-surface rounded-lg border p-3">
      <Space orientation="vertical" size="small" style={{ display: "flex" }}>
        <Input.TextArea
          data-testid="query-composer-input"
          value={query}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="例如：跨境电商专业 2025 年岗位需求分布如何？（Enter 提交，Shift/Ctrl+Enter 换行）"
          autoSize={{ minRows: 3, maxRows: 8 }}
          maxLength={MAX_QUERY_LENGTH}
          showCount
          disabled={isRunning}
        />
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-500">
            {isRunning ? "正在处理上一条问题，请等待完成…" : "支持连续追问，历史仅本页可见。"}
          </span>
          <div className="flex items-center gap-2">
            <Button onClick={onReset} disabled={isRunning}>
              清空历史
            </Button>
            <Button
              type="primary"
              onClick={onSubmit}
              loading={isRunning}
              disabled={!canSubmit}
              data-testid="query-composer-submit"
            >
              提交查询
            </Button>
          </div>
        </div>
      </Space>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Idle hint
// ---------------------------------------------------------------------------

function IdleHint() {
  return (
    <div className="border-line mx-auto max-w-lg rounded-lg border border-dashed bg-white/60 p-6 text-center text-sm text-gray-500">
      在下方输入你的检索问题。系统会：意图分类 → 参数抽取 → 工具调度 → 内容汇总，
      每一步都可点击查看输入 / 输出。
    </div>
  );
}

// ---------------------------------------------------------------------------
// Snapshot helper — freeze stream state into a turn descriptor
// ---------------------------------------------------------------------------

function snapshotTurn(
  query: string,
  createdAt: Date,
  state: UseQueryRouterStreamState,
  isStreaming: boolean,
): AgenticTurnState {
  const markdown = state.result?.markdown ?? state.rawMarkdown;
  const intent = state.result?.intent ?? state.meta?.intent ?? null;
  const intentConfidence = state.result?.intent_confidence ?? state.meta?.intent_confidence ?? null;
  const invokedTools = state.result?.invoked_tools ?? state.meta?.invoked_tools ?? [];
  const fallbackReason = state.result?.fallback_reason ?? state.meta?.fallback_reason ?? null;
  const templateId = state.meta?.template_id ?? null;
  return {
    query,
    createdAt,
    steps: state.steps,
    markdown,
    intent: typeof intent === "string" ? intent : null,
    intentConfidence,
    invokedTools,
    fallbackReason,
    warnings: state.warnings,
    templateId,
    isStreaming,
    error: state.error,
  };
}
