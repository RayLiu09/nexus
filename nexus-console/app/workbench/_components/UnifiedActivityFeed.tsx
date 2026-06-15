"use client";

import Link from "next/link";
import { ReactNode, useMemo } from "react";
import { Tabs, Tag, Tooltip } from "antd";
import { AuditOutlined, CloudUploadOutlined, ThunderboltOutlined } from "@ant-design/icons";

import { StatusLabel } from "@/components/StatusLabel";
import { EmptyState } from "@/components/shared/EmptyState";
import { formatTime } from "@/lib/format-time";
import { shortId, type AuditLog, type DataSource, type IngestBatch } from "@/lib/api";

const SOURCE_TYPE_ICON: Record<string, string> = {
  file_upload: "📤",
  nas: "📡",
  crawler: "🕷",
  database: "🗄",
  webhook: "⚡",
};

interface ActivityItem {
  id: string;
  kind: "batch" | "audit";
  timestamp: string;
  icon: ReactNode;
  title: ReactNode;
  subtitle: ReactNode;
  statusNode?: ReactNode;
  href: string;
  /** 用于在"全部"tab 中 ID hover 的提示 */
  refId?: string;
}

function batchToItem(b: IngestBatch, ds?: DataSource): ActivityItem {
  const filename =
    (b.summary.filename as string | undefined) ??
    (b.summary.package_type as string | undefined) ??
    "—";
  const href = ds ? `/data-sources/${ds.id}?tab=history` : "/data-sources";
  return {
    id: b.id,
    kind: "batch",
    timestamp: b.updated_at,
    icon: <span className="text-base">{SOURCE_TYPE_ICON[b.source_type] ?? "◎"}</span>,
    title: <span className="truncate font-medium">{filename}</span>,
    subtitle: ds ? (
      <>
        <span>{ds.name}</span>
        <Tag className="ml-2" color="default">
          {ds.source_type}
        </Tag>
      </>
    ) : (
      <span className="text-text-muted">数据源已删除</span>
    ),
    statusNode: <StatusLabel value={b.status} />,
    href,
    refId: b.id,
  };
}

function auditToItem(a: AuditLog): ActivityItem {
  // 简单规则映射：根据 event_type 染色（仅 UI 暗示，不引入语义边界）
  const eventType = a.event_type;
  const tone: "default" | "danger" | "warning" | "success" = eventType.includes("FAILED")
    ? "danger"
    : eventType.includes("REVIEW") || eventType.includes("WARN")
      ? "warning"
      : eventType.includes("COMPLETED") || eventType.includes("APPROVED")
        ? "success"
        : "default";

  // 链向 IAM 审计页（统一审计视图）
  const href = `/iam-audit?event=${encodeURIComponent(eventType)}`;

  return {
    id: a.id,
    kind: "audit",
    timestamp: a.created_at,
    icon: <AuditOutlined className="text-text-muted" />,
    title: <span className="truncate font-medium">{eventType}</span>,
    subtitle: a.actor_id ? (
      <span>
        by <code className="font-mono">{shortId(a.actor_id)}</code>
      </span>
    ) : (
      <span className="text-text-muted">system</span>
    ),
    statusNode:
      tone === "default" ? null : <Tag color={tone === "danger" ? "error" : tone}>{tone}</Tag>,
    href,
    refId: a.id,
  };
}

function ActivityRow({ item, isLast }: { item: ActivityItem; isLast: boolean }) {
  const { display, iso } = formatTime(item.timestamp);
  return (
    <Link
      href={item.href}
      className={`hover:bg-bg-alt -mx-2 grid grid-cols-[24px_1fr_auto] items-center gap-2 px-2 py-2 text-inherit no-underline ${
        isLast ? "" : "border-line-light border-b"
      }`}
    >
      <span aria-hidden>{item.icon}</span>
      <div className="min-w-0">
        <div className="flex items-center gap-2 text-sm">
          {item.title}
          {item.refId && (
            <Tooltip title={item.refId}>
              <code className="text-text-muted font-mono text-xs">{shortId(item.refId)}</code>
            </Tooltip>
          )}
        </div>
        <div className="text-text-secondary mt-0.5 truncate text-xs">{item.subtitle}</div>
      </div>
      <div className="flex flex-col items-end gap-1">
        {item.statusNode}
        <time dateTime={iso} title={iso} className="text-text-muted text-xs">
          {display}
        </time>
      </div>
    </Link>
  );
}

function ActivityList({
  items,
  emptyConfig,
}: {
  items: ActivityItem[];
  emptyConfig: { icon?: ReactNode; title: string; hint?: string };
}) {
  if (items.length === 0) {
    return (
      <EmptyState
        size="small"
        icon={emptyConfig.icon}
        title={emptyConfig.title}
        hint={emptyConfig.hint}
      />
    );
  }
  return (
    <div className="grid">
      {items.map((it, idx) => (
        <ActivityRow key={`${it.kind}:${it.id}`} item={it} isLast={idx === items.length - 1} />
      ))}
    </div>
  );
}

interface UnifiedActivityFeedProps {
  batches: IngestBatch[];
  audits: AuditLog[];
  dataSourceById: Record<string, DataSource | undefined>;
  /** 单 tab 最多展示条数，默认 10 */
  pageSize?: number;
}

export function UnifiedActivityFeed({
  batches,
  audits,
  dataSourceById,
  pageSize = 10,
}: UnifiedActivityFeedProps) {
  const batchItems = useMemo(
    () =>
      [...batches]
        .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
        .slice(0, pageSize)
        .map((b) => batchToItem(b, dataSourceById[b.data_source_id])),
    [batches, dataSourceById, pageSize],
  );
  const auditItems = useMemo(
    () =>
      [...audits]
        .sort((a, b) => b.created_at.localeCompare(a.created_at))
        .slice(0, pageSize)
        .map(auditToItem),
    [audits, pageSize],
  );
  const allItems = useMemo(
    () =>
      [...batchItems, ...auditItems]
        .sort((a, b) => b.timestamp.localeCompare(a.timestamp))
        .slice(0, pageSize),
    [batchItems, auditItems, pageSize],
  );

  return (
    <Tabs
      defaultActiveKey="all"
      size="small"
      tabBarExtraContent={
        <span className="text-text-muted flex items-center gap-1.5 text-xs">
          <ThunderboltOutlined className="text-success" />
          实时更新
        </span>
      }
      items={[
        {
          key: "all",
          label: `全部 (${allItems.length})`,
          children: (
            <ActivityList
              items={allItems}
              emptyConfig={{ title: "暂无近期活动", hint: "接入或审计事件会汇总到此" }}
            />
          ),
        },
        {
          key: "ingest",
          label: `接入 (${batchItems.length})`,
          children: (
            <ActivityList
              items={batchItems}
              emptyConfig={{
                icon: <CloudUploadOutlined />,
                title: "暂无接入活动",
                hint: "顶栏「快速上传」或定时同步会出现在这里",
              }}
            />
          ),
        },
        {
          key: "audit",
          label: `审计 (${auditItems.length})`,
          children: (
            <ActivityList
              items={auditItems}
              emptyConfig={{
                icon: <AuditOutlined />,
                title: "暂无审计事件",
                hint: "系统行为变更将在此实时记录",
              }}
            />
          ),
        },
      ]}
    />
  );
}
