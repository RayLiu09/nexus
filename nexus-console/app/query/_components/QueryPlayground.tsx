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
import { Sender } from "@ant-design/x";
import { Button, Switch } from "antd";
import { ArrowUp, Plus, Sparkles, Square } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { AgenticMessage } from "./AgenticMessage";
import type { AgenticTurnState } from "./AgenticMessage";
import { useQueryRouterStream } from "../_lib/useQueryRouterStream";
import type { UseQueryRouterStreamState } from "../_lib/useQueryRouterStream";
import styles from "./Chat.module.css";

const MAX_QUERY_LENGTH = 2048;

export function QueryPlayground() {
  const [query, setQuery] = useState("");
  const [webSearch, setWebSearch] = useState(false);
  const [history, setHistory] = useState<AgenticTurnState[]>([]);
  const [activeQuery, setActiveQuery] = useState<string | null>(null);
  const [activeCreatedAt, setActiveCreatedAt] = useState<Date | null>(null);
  const { state, start, reset, stop } = useQueryRouterStream();
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
    await start(submittedQuery, { webSearch });
  }, [canSubmit, query, start, webSearch]);

  const handleReset = useCallback(() => {
    setQuery("");
    reset();
    setActiveQuery(null);
    setActiveCreatedAt(null);
    setHistory([]);
    snapshottedRef.current = null;
  }, [reset]);

  // When streaming completes (success or error), freeze the hook's
  // state into a new turn, append to history, reset the hook. The
  // ref guard prevents double-appending if the hook state settles
  // across multiple renders.
  useEffect(() => {
    if (!activeQuery || activeCreatedAt === null) return;
    if (!["success", "error", "cancelled"].includes(state.status)) return;
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
    <div className="flex h-[calc(100dvh-190px)] min-h-[420px] w-full min-w-0 flex-col gap-4">
      <div
        ref={feedRef}
        className="min-w-0 flex-1 space-y-8 overflow-y-auto py-6"
        role="log"
        aria-live="polite"
      >
        {history.length === 0 && !activeTurn ? (
          <div className={styles.welcome}>
            <div className="mx-auto flex w-full max-w-2xl flex-col items-center text-center">
              <span className="rounded-2xl bg-indigo-50 p-4 text-indigo-600">
                <Sparkles size={30} />
              </span>
              <h2 className="mt-5 text-2xl font-semibold tracking-tight">
                从问题开始，找到有据可查的答案
              </h2>
              <p className="mt-3 text-sm leading-6 text-gray-500">
                查询业务数据、比较统计结果、查阅文档证据。
              </p>
              <div className="mt-7 grid w-full gap-3 sm:grid-cols-2">
                {[
                  "网络营销与直播电商专业有哪些核心课程？",
                  "统计重庆市电子商务专业的院校布点",
                  "市场岗位中直播运营的能力要求有哪些？",
                  "查找职业教育产教融合的相关政策",
                ].map((example) => (
                  <button
                    key={example}
                    type="button"
                    onClick={() => setQuery(example)}
                    className={styles.suggestion}
                  >
                    {example}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : null}
        {history.map((turn, idx) => (
          <AgenticMessage key={`${turn.createdAt.getTime()}-${idx}`} turn={turn} />
        ))}
        {activeTurn && <AgenticMessage key="active" turn={activeTurn} />}
      </div>
      <div className="w-full min-w-0 pb-2" data-testid="query-composer">
        <div className="mb-2 flex items-center justify-between text-xs text-gray-400">
          <Button
            type="text"
            size="small"
            onClick={handleReset}
            disabled={isRunning}
            icon={<Plus size={14} />}
          >
            新对话
          </Button>
        </div>
        <Sender
          value={query}
          onChange={(value) => setQuery(value.slice(0, MAX_QUERY_LENGTH))}
          placeholder="询问业务数据、文档或知识…"
          autoSize={{ minRows: 2, maxRows: 7 }}
          loading={isRunning}
          readOnly={isRunning}
          submitType="enter"
          onSubmit={() => void handleSubmit()}
          onCancel={stop}
          suffix={false}
          onKeyDown={(event) => {
            if ((event.nativeEvent as KeyboardEvent).isComposing && event.key === "Enter")
              return false;
          }}
          footer={(_, { components: { SendButton } }) => (
            <div className="flex w-full items-center justify-between px-1 pb-1">
              <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
                <label className="flex items-center gap-2 text-xs text-gray-600">
                  <Switch
                    size="small"
                    aria-label="联网搜索"
                    checked={webSearch}
                    onChange={setWebSearch}
                    disabled={isRunning}
                  />
                  联网搜索
                </label>
                <span className="text-xs text-gray-400">
                  Enter 发送 · Shift + Enter 换行 · {query.length}/{MAX_QUERY_LENGTH}
                </span>
              </div>
              {isRunning ? (
                <Button onClick={stop} aria-label="停止生成" icon={<Square size={14} />}>
                  停止
                </Button>
              ) : (
                <SendButton
                  type="primary"
                  disabled={!canSubmit}
                  data-testid="query-composer-submit"
                  icon={<ArrowUp size={16} />}
                >
                  发送
                </SendButton>
              )}
            </div>
          )}
        />
        <p className="mt-2 text-center text-xs text-gray-400">
          回答依据查询结果生成，请结合引用来源核对关键信息。
        </p>
      </div>
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
    externalWebResults: state.result?.external_web_results ?? [],
    citations: state.result?.citations ?? state.meta?.citations ?? [],
    cancelled: state.status === "cancelled",
  };
}
