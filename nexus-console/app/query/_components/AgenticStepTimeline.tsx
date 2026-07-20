"use client";

/**
 * B4c — vertical Agentic step timeline (left column of an assistant
 * message).
 *
 * Uses Antd's ``Timeline`` in vertical orientation. Each step maps to
 * one timeline item; the item's dot colour + label reflect the
 * step's ``status``. Clicking a label calls ``onSelect`` — the
 * enclosing message uses that to swap the right panel between "final
 * markdown" (no selection) and "step detail" (a step selected).
 */
import { Timeline } from "antd";

import type { StepPayload } from "../_lib/queryTypes";

interface AgenticStepTimelineProps {
  steps: StepPayload[];
  selectedStepId: string | null;
  onSelect: (stepId: string | null) => void;
}

export function AgenticStepTimeline({ steps, selectedStepId, onSelect }: AgenticStepTimelineProps) {
  if (steps.length === 0) {
    return (
      <p className="border-line rounded-md border border-dashed bg-gray-50 p-3 text-xs text-gray-400">
        等待执行开始…
      </p>
    );
  }

  // Antd 6 renamed Timeline `items.children` → `items.content`
  // (CLAUDE.md §四 v5→v6 migration table). The deprecated key still
  // renders but logs a warning, so use the new API.
  const items = steps.map((step) => ({
    color: dotColor(step.status),
    dot: dotIcon(step.status),
    content: <StepRow step={step} selected={step.id === selectedStepId} onSelect={onSelect} />,
  }));

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => onSelect(null)}
        className={rowButtonClass(selectedStepId === null)}
        data-testid="query-step-final"
      >
        <span className="font-medium">最终回答</span>
        <span className="text-xs text-gray-500">Markdown 输出</span>
      </button>
      <Timeline items={items} className="[&_.ant-timeline-item-content]:mt-0" />
    </div>
  );
}

interface StepRowProps {
  step: StepPayload;
  selected: boolean;
  onSelect: (stepId: string) => void;
}

function StepRow({ step, selected, onSelect }: StepRowProps) {
  const latencyMs =
    step.completed_at_ms && step.started_at_ms
      ? Math.max(0, step.completed_at_ms - step.started_at_ms)
      : null;

  return (
    <button
      type="button"
      onClick={() => onSelect(step.id)}
      className={rowButtonClass(selected)}
      data-testid={`query-step-${step.id}`}
    >
      <span className="flex items-center gap-2">
        <span className="font-medium">{step.label}</span>
        {step.status === "running" && <span className="text-xs text-blue-600">执行中…</span>}
        {step.status === "failed" && <span className="text-xs text-red-600">失败</span>}
      </span>
      <span className="text-xs text-gray-500">
        <span className="font-mono">{step.id}</span>
        {latencyMs !== null && <span className="ml-2">{latencyMs} ms</span>}
      </span>
    </button>
  );
}

function dotColor(status: StepPayload["status"]): string {
  if (status === "running") return "blue";
  if (status === "failed") return "red";
  return "green";
}

function dotIcon(status: StepPayload["status"]) {
  // Antd Timeline accepts arbitrary ReactNode for `dot`; we lean on
  // colour since @ant-design/icons adds bundle weight for something
  // the colour already conveys.
  return undefined;
}

function rowButtonClass(selected: boolean): string {
  const base =
    "flex w-full flex-col items-start rounded-md border px-3 py-2 text-left text-sm transition";
  return selected
    ? `${base} border-blue-500 bg-blue-50/60`
    : `${base} border-line bg-white hover:border-blue-300 hover:bg-blue-50/30`;
}
