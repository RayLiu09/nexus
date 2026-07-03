"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Card, Empty, Skeleton, Space, Tag, Typography } from "antd";

import type { TaskOutlineEnvelope, TaskOutlineNode, TaskOutlineProfile } from "@/lib/api";

type Props = {
  refId: string | null;
};

type ApiEnvelope =
  | {
      data: TaskOutlineEnvelope;
      error?: never;
      meta?: { trace_id?: string | null };
    }
  | {
      data?: never;
      error: { message?: string };
      meta?: { trace_id?: string | null };
    };

const NODE_LABELS: Record<string, string> = {
  book: "教材",
  project: "项目",
  task: "任务",
  task_section: "章节",
  operation_step: "步骤",
  task_artifact: "产物",
  assessment: "评价",
};

const SECTION_LABELS: Record<string, string> = {
  task_objective: "目标",
  task_background: "背景",
  task_analysis: "分析",
  knowledge_prepare: "知识准备",
  operation_steps: "任务实施",
  task_artifact: "任务产物",
  source_resource: "资源",
  task_reflection: "思考",
  assessment: "评价",
};

const SUBTYPE_LABELS: Record<string, string> = {
  theory_knowledge: "理论知识型",
  training_operation: "实训操作型",
  hybrid: "混合型",
  unknown: "未识别",
};

const GRAPH_ADMISSION_LABELS: Record<string, string> = {
  recommended: "推荐构图",
  not_recommended: "不推荐构图",
  chapter_selective: "章节选择",
  unknown: "未判定",
};

export function TaskOutlineView({ refId }: Props) {
  const [data, setData] = useState<TaskOutlineEnvelope | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!refId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/normalized-refs/${encodeURIComponent(refId)}/task-outline`,
        { cache: "no-store" },
      );
      const body = (await res.json()) as ApiEnvelope;
      if (!res.ok || body.error) {
        throw new Error(body.error?.message || `HTTP ${res.status}`);
      }
      setData(body.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [refId]);

  useEffect(() => {
    if (!refId) return;
    load();
  }, [load, refId]);

  const nodes = data?.nodes ?? [];
  const profile = data?.profile ?? null;
  const orderedNodes = useMemo(() => [...nodes].sort(compareNodes), [nodes]);

  if (!refId) {
    return (
      <Card className="!mt-4" title="任务大纲">
        <Alert type="info" showIcon title="该资产尚无标准化引用，暂无任务大纲。" />
      </Card>
    );
  }

  return (
    <Card
      className="!mt-4"
      title={
        <Space wrap>
          <span>任务大纲</span>
          {profile?.textbook_subtype ? (
            <Tag color={profile.textbook_subtype === "training_operation" ? "blue" : "default"}>
              {SUBTYPE_LABELS[profile.textbook_subtype] ?? profile.textbook_subtype}
            </Tag>
          ) : null}
          {profile?.evidence_graph_admission ? (
            <Tag color={profile.evidence_graph_admission === "not_recommended" ? "warning" : "green"}>
              {GRAPH_ADMISSION_LABELS[profile.evidence_graph_admission] ??
                profile.evidence_graph_admission}
            </Tag>
          ) : null}
          {data?.chunk_projection.projected_chunk_count ? (
            <Tag color="processing">{data.chunk_projection.projected_chunk_count} chunks</Tag>
          ) : null}
        </Space>
      }
    >
      {error ? <Alert type="error" showIcon className="!mb-3" title={error} /> : null}
      {loading && data === null ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : !profile ? (
        <Empty description="该 ref 暂未构建任务大纲。" />
      ) : orderedNodes.length === 0 ? (
        <Empty description="该任务大纲暂无节点。" />
      ) : (
        <div className="flex flex-col divide-y divide-line">
          <ProfileSummary profile={profile} />
          {orderedNodes.map((node) => (
            <NodeRow key={node.id} node={node} />
          ))}
        </div>
      )}
    </Card>
  );
}

function ProfileSummary({ profile }: { profile: TaskOutlineProfile }) {
  const quality = profile.quality ?? {};
  return (
    <div className="grid gap-2 py-3 text-xs text-text-muted md:grid-cols-4">
      <Metric label="处理方式" value={profile.processing_profile} />
      <Metric
        label="置信度"
        value={profile.subtype_confidence === null ? "-" : `${Math.round(profile.subtype_confidence * 100)}%`}
      />
      <Metric label="节点质量" value={quality.review_required ? "需复核" : "通过"} />
      <Metric
        label="定位覆盖"
        value={typeof quality.locator_coverage === "number" ? `${Math.round(quality.locator_coverage * 100)}%` : "-"}
      />
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <span className="block text-text-tertiary">{label}</span>
      <strong className="block truncate text-text-secondary">{value}</strong>
    </div>
  );
}

function NodeRow({ node }: { node: TaskOutlineNode }) {
  const label = node.section_type
    ? SECTION_LABELS[node.section_type] ?? node.section_type
    : NODE_LABELS[node.node_type] ?? node.node_type;
  const pageRange = formatPageRange(node.locator);
  const content = node.summary || node.content;
  const indent = Math.max(0, Math.min(node.depth, 5)) * 18;

  return (
    <div className="py-3" style={{ paddingLeft: indent }}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <Space size={6} wrap>
            <Tag className="!m-0" color={node.node_type === "operation_step" ? "blue" : "default"}>
              {label}
            </Tag>
            <Typography.Text strong className="max-w-full">
              {node.title || "(未命名节点)"}
            </Typography.Text>
          </Space>
          {content ? (
            <Typography.Paragraph
              className="!mb-0 !mt-1 text-sm text-text-secondary"
              ellipsis={{ rows: 2, expandable: false }}
            >
              {content}
            </Typography.Paragraph>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-1 text-xs text-text-tertiary">
          {pageRange ? <Tag className="!m-0">{pageRange}</Tag> : null}
          {node.source_block_ids.length > 0 ? (
            <Tag className="!m-0">{node.source_block_ids.length} blocks</Tag>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function compareNodes(a: TaskOutlineNode, b: TaskOutlineNode) {
  if (a.depth !== b.depth) return a.depth - b.depth;
  if (a.order_no !== b.order_no) return a.order_no - b.order_no;
  return a.id.localeCompare(b.id);
}

function formatPageRange(locator: Record<string, unknown> | null): string | null {
  if (!locator) return null;
  const start = locator.page_start;
  const end = locator.page_end;
  if (typeof start !== "number") return null;
  if (typeof end === "number" && end !== start) return `p${start}-${end}`;
  return `p${start}`;
}
