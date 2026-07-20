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
import { Alert, Button, Tag } from "antd";

import type { KnowledgeChunkHit } from "@/lib/chunkTypes";

import type { StepPayload } from "../_lib/queryTypes";

interface StepDetailPanelProps {
  step: StepPayload;
  onSelectChunk?: (chunk: KnowledgeChunkHit) => void;
}

export function StepDetailPanel({ step, onSelectChunk }: StepDetailPanelProps) {
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

      {onSelectChunk && <RetrievedChunks value={step.output} onSelectChunk={onSelectChunk} />}
    </div>
  );
}

function RetrievedChunks({
  value,
  onSelectChunk,
}: {
  value: unknown;
  onSelectChunk: (chunk: KnowledgeChunkHit) => void;
}) {
  const chunks = collectChunkHits(value);
  if (chunks.length === 0) return null;
  return (
    <section>
      <h3 className="mb-2 text-xs font-medium tracking-wider text-gray-500 uppercase">
        检索知识块
      </h3>
      <div className="flex flex-col items-start gap-1">
        {chunks.map((chunk) => (
          <Button
            key={chunk.nexus_chunk_id ?? chunk.chunk_id}
            type="link"
            size="small"
            className="h-auto max-w-full px-0 text-left"
            data-testid={`query-retrieval-chunk-${chunk.nexus_chunk_id ?? chunk.chunk_id}`}
            onClick={() => onSelectChunk(chunk)}
          >
            <span className="block truncate font-mono text-xs">
              {chunk.content || chunk.nexus_chunk_id || chunk.chunk_id}
            </span>
          </Button>
        ))}
      </div>
    </section>
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

function collectChunkHits(value: unknown): KnowledgeChunkHit[] {
  const chunks: KnowledgeChunkHit[] = [];
  const seen = new Set<string>();
  const visit = (item: unknown): void => {
    if (chunks.length >= 24 || item === null || item === undefined) return;
    if (Array.isArray(item)) {
      item.forEach(visit);
      return;
    }
    if (typeof item !== "object") return;
    const record = item as Record<string, unknown>;
    const chunkId = stringValue(record.nexus_chunk_id) ?? stringValue(record.chunk_id);
    if (chunkId && !seen.has(chunkId)) {
      seen.add(chunkId);
      chunks.push({
        chunk_id: chunkId,
        nexus_chunk_id: chunkId,
        id: chunkId,
        content: stringValue(record.content) ?? "",
        normalized_ref_id: stringValue(record.normalized_ref_id),
        score: numberValue(record.score),
      });
    }
    Object.values(record).forEach(visit);
  };
  visit(value);
  return chunks;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function numberValue(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}
