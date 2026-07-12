"use client";

import { Progress, Space, Tag, Typography } from "antd";
import { AlertTriangle, CheckCircle2, Clock3, Loader2, Settings2 } from "lucide-react";

import type { RetrievalConversationStep, RetrievalResult } from "@/lib/retrievalTypes";

import { InlineJsonPreview, statusColor, statusLabel } from "../_lib/playgroundHelpers";

interface ExecutionStepsProps {
  steps: RetrievalConversationStep[];
  results: RetrievalResult[];
  compact?: boolean;
}

export function ExecutionSteps({ steps, results, compact = false }: ExecutionStepsProps) {
  const completed = steps.filter((step) => step.status === "completed").length;
  const progress = steps.length ? Math.round((completed / steps.length) * 100) : 0;

  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--surface-alt)] p-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Space>
          <Settings2 size={16} aria-hidden="true" />
          <Typography.Text strong>执行过程</Typography.Text>
          <Tag color="processing">{steps.length} 步</Tag>
        </Space>
        <Progress percent={progress} size="small" className="max-w-48" />
      </div>

      <div
        className={
          compact
            ? "grid grid-cols-1 gap-3 md:grid-cols-3"
            : "grid grid-cols-1 gap-3 lg:grid-cols-5"
        }
      >
        {steps.map((step, index) => (
          <StepTile
            key={`${step.step}-${index}`}
            step={step}
            index={index}
            relatedResults={step.step === "parallel_retrieval" ? results : []}
          />
        ))}
      </div>
    </div>
  );
}

interface StepTileProps {
  step: RetrievalConversationStep;
  index: number;
  relatedResults: RetrievalResult[];
}

function StepTile({ step, index, relatedResults }: StepTileProps) {
  return (
    <div className="min-h-32 rounded-lg border border-[var(--line)] bg-[var(--surface)] p-3">
      <div className="mb-2 flex items-start justify-between gap-2">
        <Space size="small" align="start">
          <StepIcon status={step.status} />
          <div>
            <Typography.Text strong className="block">
              {index + 1}. {step.title}
            </Typography.Text>
            <Tag color={statusColor(step.status)} className="mt-1">
              {statusLabel(step.status)}
            </Tag>
          </div>
        </Space>
      </div>
      {step.message && (
        <Typography.Paragraph type="secondary" className="!mb-2 text-xs">
          {step.message}
        </Typography.Paragraph>
      )}
      {step.progress && Object.keys(step.progress).length > 0 && (
        <InlineJsonPreview value={step.progress} maxHeight="max-h-24" />
      )}
      {step.display_payload && Object.keys(step.display_payload).length > 0 && (
        <div className="mt-2">
          <InlineJsonPreview value={step.display_payload} maxHeight="max-h-40" />
        </div>
      )}
      {relatedResults.length > 0 && (
        <div className="mt-2 space-y-1">
          {relatedResults.map((result) => (
            <Typography.Text key={result.query_id} type="secondary" className="block text-xs">
              {result.query_id} · {result.domain} · {result.result_shape ?? "-"} ·{" "}
              {statusLabel(result.status)}
            </Typography.Text>
          ))}
        </div>
      )}
    </div>
  );
}

export function StepIcon({ status }: { status: string }) {
  const className = "mt-0.5 shrink-0";
  if (status === "running") return <Loader2 size={16} className={`${className} animate-spin`} />;
  if (status === "completed") return <CheckCircle2 size={16} className={className} />;
  if (status === "failed" || status === "blocked")
    return <AlertTriangle size={16} className={className} />;
  return <Clock3 size={16} className={className} />;
}
