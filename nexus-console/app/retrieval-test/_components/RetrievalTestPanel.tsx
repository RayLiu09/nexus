"use client";

import { Card, Spin, Tag } from "antd";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useState } from "react";

import { ApiState } from "@/components/ApiState";
import type { KnowledgeRetrievalResponse } from "@/lib/retrievalTypes";

import type { FixturePreset } from "./fixtures.types";
import { IntentCard } from "./IntentCard";
import { PlanSection } from "./PlanSection";
import { QueryForm, type QueryMode } from "./QueryForm";
import { ResultTabs } from "./ResultTabs";
import { WarningsPanel } from "./WarningsPanel";

interface RetrievalTestPanelProps {
  presets: FixturePreset[];
}

interface ProxySuccess<T> {
  ok: true;
  data: T;
  traceId: string | null;
}

interface ProxyError {
  ok: false;
  status: number;
  message: string;
}

type ProxyBody<T> = ProxySuccess<T> | ProxyError;

interface RunState {
  data: KnowledgeRetrievalResponse | null;
  mode: QueryMode | null;
  error: string | null;
  traceId: string | null;
  submitting: boolean;
}

const INITIAL_STATE: RunState = {
  data: null,
  mode: null,
  error: null,
  traceId: null,
  submitting: false,
};

export function RetrievalTestPanel({ presets }: RetrievalTestPanelProps) {
  const [state, setState] = useState<RunState>(INITIAL_STATE);

  const handleSubmit = async (query: string, mode: QueryMode): Promise<void> => {
    setState({ ...INITIAL_STATE, submitting: true, mode });

    const endpoint =
      mode === "plan" ? "/api/knowledge-retrieval/plans" : "/api/knowledge-retrieval";
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ query }),
        cache: "no-store",
      });
      const body = (await res.json()) as ProxyBody<KnowledgeRetrievalResponse>;
      if (!body.ok) {
        setState({
          data: null,
          mode,
          error: body.message || `请求失败 (HTTP ${body.status})`,
          traceId: null,
          submitting: false,
        });
        return;
      }
      setState({
        data: body.data,
        mode,
        error: null,
        traceId: body.traceId,
        submitting: false,
      });
    } catch (err) {
      setState({
        data: null,
        mode,
        error: err instanceof Error ? err.message : String(err),
        traceId: null,
        submitting: false,
      });
    }
  };

  return (
    <div className="flex flex-col gap-4" data-testid="retrieval-test-panel">
      <QueryForm
        presets={presets}
        submitting={state.submitting}
        onSubmit={handleSubmit}
      />

      {state.error && (
        <ApiState ok={false} error={state.error} traceId={state.traceId} />
      )}

      {state.submitting && (
        <Card size="small">
          <Spin tip="正在执行 orchestrator…">
            <div className="min-h-24" />
          </Spin>
        </Card>
      )}

      {state.data && !state.submitting && (
        <ResponseView data={state.data} mode={state.mode ?? "plan"} />
      )}
    </div>
  );
}

interface ResponseViewProps {
  data: KnowledgeRetrievalResponse;
  mode: QueryMode;
}

function ResponseView({ data, mode }: ResponseViewProps) {
  return (
    <div className="flex flex-col gap-4" data-testid="response-view">
      <Card size="small">
        <div className="flex flex-wrap items-center gap-2">
          <Tag color={statusColor(data.status)}>{data.status}</Tag>
          <span className="text-xs text-gray-500">query_id</span>
          <span className="font-mono text-xs">{data.query_id}</span>
          <span className="text-xs text-gray-500">access_scope</span>
          <Tag>{data.access_scope}</Tag>
          <span className="ml-auto text-xs text-gray-400">
            {mode === "plan" ? "Plan Only 模式 — 不执行 executors" : "Full Run 模式"}
          </span>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="lg:col-span-1" data-testid="intent-slot">
          <IntentCard intent={data.intent} />
        </div>
        <div className="lg:col-span-1" data-testid="plan-slot">
          <PlanSection plan={data.retrieval_plan ?? null} />
        </div>
      </div>

      {mode === "full" && (
        <div data-testid="results-slot">
          <ResultTabs data={data} />
        </div>
      )}

      <div data-testid="warnings-slot">
        <WarningsPanel warnings={data.warnings} />
      </div>

      {mode === "full" && data.markdown && (
        <Card size="small" title="LLM Markdown 汇总" data-testid="markdown-slot">
          <div className="prose max-w-none text-sm">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{data.markdown}</ReactMarkdown>
          </div>
        </Card>
      )}
    </div>
  );
}

function statusColor(
  status: KnowledgeRetrievalResponse["status"],
): "success" | "warning" | "processing" | "error" | "default" {
  switch (status) {
    case "completed":
      return "success";
    case "partial":
    case "needs_clarification":
      return "warning";
    case "planned":
    case "running":
      return "processing";
    case "failed":
      return "error";
    default:
      return "default";
  }
}
