"use client";

import { Alert, Button, Collapse, Empty, Space, Tag, Typography } from "antd";
import { Database, FileSearch, ListChecks, Split } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { KnowledgeRetrievalResponse } from "@/lib/retrievalTypes";

import type { ConversationMessage } from "../_lib/playgroundTypes";
import {
  CollapseLabel,
  ResultSectionTitle,
  buildLiveRetrievalSteps,
  statusLabel,
} from "../_lib/playgroundHelpers";

import { ExecutionSteps } from "./ExecutionSteps";
import {
  IntentAnalysisPanel,
  RetrievalPlanPanel,
  RetrievalResultList,
  SourceRefList,
} from "./RetrievalDetailPanels";
import { RunningNotice } from "./RunningNotice";

interface RetrievalConversationResultProps {
  message: ConversationMessage;
  progressTick: number;
  onApplyRefinement: (text: string) => void;
}

export function RetrievalConversationResult({
  message,
  progressTick,
  onApplyRefinement,
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

      {data && (
        <Collapse
          ghost
          defaultActiveKey={data.status === "needs_clarification" ? ["intent", "plan"] : ["intent"]}
          items={[
            {
              key: "intent",
              label: <CollapseLabel icon={<Split size={15} />} text="意图识别辅助分析" />,
              children: <IntentAnalysisPanel data={data} />,
            },
            {
              key: "plan",
              label: <CollapseLabel icon={<ListChecks size={15} />} text="召回计划" />,
              children: <RetrievalPlanPanel data={data} />,
            },
            {
              key: "results",
              label: (
                <CollapseLabel
                  icon={<Database size={15} />}
                  text={`执行结果 (${data.retrieval_results.length})`}
                />
              ),
              children: <RetrievalResultList results={data.retrieval_results} />,
            },
            {
              key: "sources",
              label: (
                <CollapseLabel
                  icon={<FileSearch size={15} />}
                  text={`来源与定位 (${data.source_refs.length})`}
                />
              ),
              children: <SourceRefList refs={data.source_refs} />,
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
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{data.markdown}</ReactMarkdown>
        </div>
      ) : (
        <Empty description="本次召回没有生成 Markdown 结果" />
      )}
      {data.warnings.length > 0 && (
        <Alert
          type="warning"
          showIcon
          className="mt-4"
          title="结果警告"
          description={data.warnings.join("；")}
        />
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
    <div className="rounded-lg border border-[var(--warning-100)] bg-[var(--warning-bg)] p-4">
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
          <Typography.Text strong>可继续追问</Typography.Text>
          <div className="mt-2 flex flex-wrap gap-2">
            {refinements.map((item) => (
              <Button key={item} size="small" onClick={() => onApplyRefinement(item)}>
                {item}
              </Button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
