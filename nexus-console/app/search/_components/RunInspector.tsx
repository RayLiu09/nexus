"use client";

import { Empty, Progress, Space, Typography } from "antd";
import { Database } from "lucide-react";

import type { ConversationMessage } from "../_lib/playgroundTypes";
import { MODE_LABELS } from "../_lib/playgroundTypes";
import { MetricBox, buildLiveRetrievalSteps, statusLabel } from "../_lib/playgroundHelpers";

import { StepIcon } from "./ExecutionSteps";

interface RunInspectorProps {
  latestAssistant: ConversationMessage | undefined;
  progressTick: number;
}

export function RunInspector({ latestAssistant, progressTick }: RunInspectorProps) {
  const data = latestAssistant?.retrievalData;
  const steps =
    latestAssistant?.status === "running"
      ? buildLiveRetrievalSteps(progressTick)
      : (data?.conversation_steps ?? []);
  const activeStep =
    steps.find((step) => step.status === "running") ??
    [...steps].reverse().find((step) => step.status === "completed") ??
    null;

  return (
    <aside className="rounded-lg border border-[var(--line)] bg-[var(--surface)] p-4">
      <Space orientation="vertical" size="middle" className="w-full">
        <Space>
          <Database size={16} aria-hidden="true" />
          <Typography.Text strong>执行观察</Typography.Text>
        </Space>

        {!latestAssistant ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无执行任务" />
        ) : (
          <>
            <div className="rounded-lg bg-[var(--surface-alt)] p-3">
              <Typography.Text type="secondary" className="block">
                当前问题
              </Typography.Text>
              <Typography.Paragraph className="mt-1 !mb-0">
                {latestAssistant.query}
              </Typography.Paragraph>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <MetricBox label="模式" value={MODE_LABELS[latestAssistant.mode]} />
              <MetricBox label="状态" value={statusLabel(latestAssistant.status)} />
              <MetricBox
                label="步骤"
                value={
                  steps.length
                    ? `${steps.filter((s) => s.status === "completed").length}/${steps.length}`
                    : "-"
                }
              />
              <MetricBox label="来源" value={data ? String(data.source_refs.length) : "-"} />
            </div>

            {activeStep && (
              <div className="rounded-lg border border-[var(--line)] p-3">
                <Typography.Text type="secondary" className="block">
                  当前步骤
                </Typography.Text>
                <Space className="mt-2">
                  <StepIcon status={activeStep.status} />
                  <Typography.Text strong>{activeStep.title}</Typography.Text>
                </Space>
                {activeStep.message && (
                  <Typography.Paragraph type="secondary" className="mt-2 !mb-0 text-sm">
                    {activeStep.message}
                  </Typography.Paragraph>
                )}
              </div>
            )}

            {data?.intent && (
              <div className="rounded-lg border border-[var(--line)] p-3">
                <Typography.Text type="secondary" className="block">
                  识别置信度
                </Typography.Text>
                <Progress
                  percent={Math.round(data.intent.confidence * 100)}
                  size="small"
                  status={
                    data.intent.confidence >= data.intent.confidence_threshold
                      ? "success"
                      : "exception"
                  }
                />
              </div>
            )}
          </>
        )}
      </Space>
    </aside>
  );
}
