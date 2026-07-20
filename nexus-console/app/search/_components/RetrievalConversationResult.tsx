"use client";

import { Alert, Button, Collapse, Empty, Space, Tag, Typography } from "antd";
import { Database, FileSearch, ListChecks, Split } from "lucide-react";

import { FriendlyPlanView } from "@/components/retrieval/FriendlyPlanView";
import { IntentCard } from "@/components/retrieval/IntentCard";
import { PlanSection } from "@/components/retrieval/PlanSection";
import { ResultTabs } from "@/components/retrieval/ResultTabs";
import { WarningsPanel } from "@/components/retrieval/WarningsPanel";
import type { KnowledgeRetrievalResponse, RetrievalSourceRef } from "@/lib/retrievalTypes";

import { QueryRouterAnswer } from "../../query/_components/QueryRouterAnswer";

import type { ConversationMessage } from "../_lib/playgroundTypes";
import {
  CollapseLabel,
  ResultSectionTitle,
  buildLiveRetrievalSteps,
  statusLabel,
} from "../_lib/playgroundHelpers";

import { ExecutionSteps } from "./ExecutionSteps";
import { RunningNotice } from "./RunningNotice";

interface RetrievalConversationResultProps {
  message: ConversationMessage;
  progressTick: number;
  onApplyRefinement: (text: string) => void;
  onSelectSourceRef?: (ref: RetrievalSourceRef) => void;
}

export function RetrievalConversationResult({
  message,
  progressTick,
  onApplyRefinement,
  onSelectSourceRef,
}: RetrievalConversationResultProps) {
  const data = message.retrievalData;
  const steps = data?.conversation_steps?.length
    ? data.conversation_steps
    : buildLiveRetrievalSteps(progressTick);
  const results = data?.retrieval_results ?? [];

  return (
    <Space orientation="vertical" size="middle" className="w-full">
      <ExecutionSteps steps={steps} results={results} />

      {!data ? (
        <RunningNotice query={message.query} />
      ) : data.status === "needs_clarification" ? (
        <ClarificationPanel data={data} onApplyRefinement={onApplyRefinement} />
      ) : (
        <MarkdownAnswer data={data} />
      )}

      {/*
        FriendlyView is the v1.3 §5.5 planner-emitted natural-language
        projection meant for direct user consumption. Show it before the
        technical Collapse so users see reasoning first; only render when
        the backend actually attached one (v1.2 responses / partial
        results don't have it and we prefer silence over a placeholder in
        the conversation stream).
       */}
      {data?.retrieval_plan?.friendly_view && (
        <FriendlyPlanView friendlyView={data.retrieval_plan.friendly_view} />
      )}

      {data && (
        <Collapse
          ghost
          defaultActiveKey={data.status === "needs_clarification" ? ["intent", "plan"] : ["intent"]}
          items={[
            {
              key: "intent",
              label: <CollapseLabel icon={<Split size={15} />} text="意图识别" />,
              children: <IntentCard intent={data.intent} />,
            },
            {
              key: "plan",
              label: <CollapseLabel icon={<ListChecks size={15} />} text="检索计划" />,
              children: <PlanSection plan={data.retrieval_plan ?? null} />,
            },
            {
              key: "results",
              label: (
                <CollapseLabel
                  icon={<Database size={15} />}
                  text={`执行结果 (${data.retrieval_results.length})`}
                />
              ),
              children: <ResultTabs data={data} onSelectSourceRef={onSelectSourceRef} />,
            },
            {
              key: "warnings",
              label: (
                <CollapseLabel
                  icon={<FileSearch size={15} />}
                  text={`告警 (${data.warnings.length})`}
                />
              ),
              children: <WarningsPanel warnings={data.warnings} />,
            },
          ]}
        />
      )}
    </Space>
  );
}

function MarkdownAnswer({ data }: { data: KnowledgeRetrievalResponse }) {
  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--surface-alt)] p-4">
      <ResultSectionTitle
        title="结构化结果"
        tags={[
          statusLabel(data.status),
          `来源 ${data.source_refs.length}`,
          `范围 ${data.access_scope}`,
        ]}
      />
      {data.markdown ? (
        <div className="prose max-w-none leading-7">
          <QueryRouterAnswer markdown={data.markdown} />
        </div>
      ) : (
        <Empty description="本次召回没有生成 Markdown 结果" />
      )}
    </div>
  );
}

interface ClarificationPanelProps {
  data: KnowledgeRetrievalResponse;
  onApplyRefinement: (text: string) => void;
}

function ClarificationPanel({ data, onApplyRefinement }: ClarificationPanelProps) {
  const clarification = data.clarification;
  const refinements = clarification?.suggested_refinements?.length
    ? clarification.suggested_refinements
    : (data.intent.suggested_refinements ?? []);

  return (
    <div
      className="rounded-lg border border-[var(--warning-100)] bg-[var(--warning-bg)] p-4"
      data-testid="clarification-panel"
    >
      <Alert
        type="warning"
        showIcon
        title={clarification?.message ?? "当前问题的检索意图不够清晰。"}
      />
      {clarification?.missing_constraints?.length ? (
        <div className="mt-4">
          <Typography.Text strong>缺失约束</Typography.Text>
          <Space wrap className="ml-2">
            {clarification.missing_constraints.map((item) => (
              <Tag key={item}>{item}</Tag>
            ))}
          </Space>
        </div>
      ) : null}
      {refinements.length > 0 && (
        <div className="mt-4">
          <Typography.Text strong>快捷追问（点击即自动重跑）</Typography.Text>
          <div className="mt-2 flex flex-wrap gap-2" data-testid="clarification-refinements">
            {refinements.map((item) => (
              <Button
                key={item}
                size="small"
                type="primary"
                ghost
                onClick={() => onApplyRefinement(item)}
              >
                {item}
              </Button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
