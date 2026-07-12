"use client";

import { Card, Empty, Tabs, Tag } from "antd";
import { FileSearch } from "lucide-react";
import { useMemo } from "react";

import type {
  KnowledgeRetrievalResponse,
  RetrievalConversationStep,
  RetrievalResult,
  RetrievalSourceRef,
} from "@/lib/retrievalTypes";

import { JsonPreview } from "./JsonPreview";

interface ResultTabsProps {
  data: KnowledgeRetrievalResponse;
}

export function ResultTabs({ data }: ResultTabsProps) {
  const counts = useMemo(() => {
    const records = data.retrieval_results.reduce((n, r) => n + (r.records?.length ?? 0), 0);
    const items = data.retrieval_results.reduce((n, r) => n + (r.items?.length ?? 0), 0);
    const aggregations = data.retrieval_results.reduce(
      (n, r) => n + (r.aggregations?.length ?? 0),
      0,
    );
    return {
      records,
      items,
      aggregations,
      sourceRefs: data.source_refs.length,
      steps: data.conversation_steps.length,
    };
  }, [data]);

  return (
    <Card
      size="small"
      title={
        <span className="inline-flex items-center gap-2">
          <FileSearch size={16} className="text-brand" />
          执行结果
        </span>
      }
    >
      <Tabs
        defaultActiveKey="records"
        items={[
          {
            key: "records",
            label: `records (${counts.records})`,
            children: <ResultsList results={data.retrieval_results} kind="records" />,
          },
          {
            key: "items",
            label: `items (${counts.items})`,
            children: <ResultsList results={data.retrieval_results} kind="items" />,
          },
          {
            key: "aggregations",
            label: `aggregations (${counts.aggregations})`,
            children: <ResultsList results={data.retrieval_results} kind="aggregations" />,
          },
          {
            key: "source_refs",
            label: `source_refs (${counts.sourceRefs})`,
            children: <SourceRefsView refs={data.source_refs} />,
          },
          {
            key: "steps",
            label: `conversation_steps (${counts.steps})`,
            children: <StepsView steps={data.conversation_steps} />,
          },
        ]}
      />
    </Card>
  );
}

type ResultKind = "records" | "items" | "aggregations";

interface ResultsListProps {
  results: RetrievalResult[];
  kind: ResultKind;
}

function ResultsList({ results, kind }: ResultsListProps) {
  const nonEmpty = results.filter((r) => (r[kind]?.length ?? 0) > 0);
  if (nonEmpty.length === 0) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={`当前执行没有产生 ${kind}`} />;
  }
  return (
    <div className="flex flex-col gap-4">
      {nonEmpty.map((r) => (
        <div key={`${r.query_id}-${kind}`}>
          <div className="mb-2 flex items-center gap-2">
            <Tag color="blue">{r.query_id}</Tag>
            <Tag color="geekblue">{r.channel}</Tag>
            <Tag color="cyan">{r.domain}</Tag>
            <Tag>{r.status}</Tag>
            {r.result_shape && <Tag color="purple">{r.result_shape}</Tag>}
            {r.elapsed_ms != null && (
              <span className="text-xs text-gray-500">{r.elapsed_ms.toFixed(1)} ms</span>
            )}
          </div>
          <JsonPreview value={r[kind]} maxHeight={360} label={`${r.query_id}.${kind}`} />
        </div>
      ))}
    </div>
  );
}

function SourceRefsView({ refs }: { refs: RetrievalSourceRef[] }) {
  if (refs.length === 0) {
    return (
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前执行没有产生 source_refs" />
    );
  }
  return (
    <div className="flex flex-col gap-2">
      {refs.map((ref) => (
        <div
          key={ref.source_ref_id}
          className="border-line flex flex-col gap-1 rounded-md border p-3"
        >
          <div className="flex flex-wrap items-center gap-2">
            <Tag color="blue">{ref.source_ref_id}</Tag>
            <Tag color="geekblue">{ref.channel}</Tag>
            <Tag color="cyan">{ref.domain}</Tag>
            {ref.score != null && <Tag color="green">{ref.score.toFixed(3)}</Tag>}
          </div>
          <span className="text-xs text-gray-600">
            asset={ref.asset_id ?? "-"} · version={ref.asset_version_id ?? "-"} · ref=
            {ref.normalized_ref_id ?? "-"}
          </span>
          <span className="text-xs text-gray-600">
            {ref.chunk_id ?? ref.record_ref ?? "无 chunk / record 定位"}
          </span>
          {ref.locator && Object.keys(ref.locator).length > 0 && (
            <JsonPreview
              value={ref.locator}
              maxHeight={160}
              label={`${ref.source_ref_id}.locator`}
            />
          )}
        </div>
      ))}
    </div>
  );
}

function StepsView({ steps }: { steps: RetrievalConversationStep[] }) {
  if (steps.length === 0) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无 conversation_steps" />;
  }
  return (
    <div className="flex flex-col gap-2">
      {steps.map((step, idx) => (
        <div key={`${step.step}-${idx}`} className="border-line rounded-md border p-3">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <Tag color="blue">{step.step}</Tag>
            <Tag color={step.status === "completed" ? "success" : "warning"}>{step.status}</Tag>
            <span className="text-sm font-medium">{step.title}</span>
          </div>
          {step.message && <div className="text-xs text-gray-600">{step.message}</div>}
          {step.display_payload && (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs text-gray-500">display_payload</summary>
              <div className="mt-2">
                <JsonPreview
                  value={step.display_payload}
                  maxHeight={200}
                  label={`${step.step}.payload`}
                />
              </div>
            </details>
          )}
        </div>
      ))}
    </div>
  );
}
