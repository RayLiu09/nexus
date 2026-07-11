"use client";

import { Card, Collapse, Empty, Tag } from "antd";
import { Split } from "lucide-react";

import type { RetrievalPlan, RetrievalSubQuery } from "@/lib/retrievalTypes";

import { JsonPreview } from "./JsonPreview";

interface PlanSectionProps {
  plan: RetrievalPlan | null | undefined;
}

export function PlanSection({ plan }: PlanSectionProps) {
  return (
    <Card
      size="small"
      title={
        <span className="inline-flex items-center gap-2">
          <Split size={16} className="text-brand" />
          检索计划 {plan ? `(${plan.sub_queries.length} 个子查询)` : ""}
        </span>
      }
    >
      {!plan ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="orchestrator 选择了 direct-retrieve 路径，未生成 planner 计划"
        />
      ) : (
        <div className="flex flex-col gap-3">
          <div className="text-sm text-gray-600">
            <span className="font-medium">合并目标：</span>
            {plan.merge_goal || "（未指定）"}
          </div>
          <Collapse
            size="small"
            items={plan.sub_queries.map((sub) => ({
              key: sub.query_id,
              label: <SubQueryHeader sub={sub} />,
              children: <SubQueryBody sub={sub} />,
            }))}
          />
        </div>
      )}
    </Card>
  );
}

function SubQueryHeader({ sub }: { sub: RetrievalSubQuery }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="font-mono text-xs text-gray-500">{sub.query_id}</span>
      <Tag color="blue">{sub.channel}</Tag>
      <Tag color="geekblue">{sub.domain}</Tag>
      <span className="text-sm text-gray-700">{sub.purpose}</span>
      <span className="ml-auto max-w-md truncate text-xs text-gray-500">
        {sub.query_text}
      </span>
    </div>
  );
}

function SubQueryBody({ sub }: { sub: RetrievalSubQuery }) {
  const planPayload = sub.structured_plan ?? sub.unstructured_plan;
  const planKind = sub.structured_plan
    ? "structured_plan"
    : sub.unstructured_plan
      ? "unstructured_plan"
      : null;

  return (
    <div className="flex flex-col gap-3">
      <div className="text-xs text-gray-600">
        <span className="font-medium">query_text：</span>
        {sub.query_text}
      </div>
      {planKind && planPayload && (
        <div>
          <div className="mb-1 text-xs font-medium text-gray-700">{planKind}</div>
          <JsonPreview value={planPayload} maxHeight={240} label={planKind} />
        </div>
      )}
    </div>
  );
}
