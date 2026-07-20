"use client";

/**
 * B4c — right-pane step detail viewer.
 *
 * Shows one selected pipeline step's input/output/status/latency.
 * Payloads render as monospaced JSON blocks (no live JS eval, no
 * hover magic — keep it readable and copy-paste friendly).  Empty
 * ``output`` (running step) renders a subtle placeholder rather than
 * `null` so operators can distinguish "still executing" from "no
 * output produced".
 */
import { Alert, Tag } from "antd";

import type { StepPayload } from "../_lib/queryTypes";

interface StepDetailPanelProps {
  step: StepPayload;
}

export function StepDetailPanel({ step }: StepDetailPanelProps) {
  const latencyMs =
    step.completed_at_ms && step.started_at_ms
      ? Math.max(0, step.completed_at_ms - step.started_at_ms)
      : null;

  return (
    <div className="space-y-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-base font-medium">{step.label}</span>
        <StatusTag status={step.status} />
        <Tag color="default" className="font-mono text-xs">
          {step.id}
        </Tag>
        {latencyMs !== null && (
          <Tag color="default" className="text-xs">
            {latencyMs} ms
          </Tag>
        )}
      </div>

      {step.error && <Alert type="error" title="步骤失败" description={step.error} showIcon />}

      <section>
        <h3 className="mb-2 text-xs font-medium tracking-wider text-gray-500 uppercase">输入</h3>
        <JsonBlock value={step.input} emptyHint="无输入" />
      </section>

      <section>
        <h3 className="mb-2 text-xs font-medium tracking-wider text-gray-500 uppercase">输出</h3>
        {step.output === null && step.status === "running" ? (
          <p className="border-line rounded-md border border-dashed bg-gray-50 p-3 text-xs text-gray-400">
            步骤执行中，输出尚未产出…
          </p>
        ) : (
          <JsonBlock value={step.output ?? {}} emptyHint="无输出" />
        )}
      </section>
    </div>
  );
}

interface StatusTagProps {
  status: StepPayload["status"];
}

function StatusTag({ status }: StatusTagProps) {
  if (status === "running") return <Tag color="processing">执行中</Tag>;
  if (status === "failed") return <Tag color="error">失败</Tag>;
  return <Tag color="success">完成</Tag>;
}

interface JsonBlockProps {
  value: unknown;
  emptyHint: string;
}

function JsonBlock({ value, emptyHint }: JsonBlockProps) {
  const isEmptyObject =
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value as Record<string, unknown>).length === 0;
  if (isEmptyObject) {
    return (
      <p className="border-line rounded-md border border-dashed bg-gray-50 p-3 text-xs text-gray-400">
        {emptyHint}
      </p>
    );
  }
  return (
    <pre className="border-line max-h-[420px] overflow-auto rounded-md border bg-gray-50 p-3 text-xs leading-relaxed">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}
