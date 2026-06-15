"use client";

import Link from "next/link";
import { Tag, Tooltip } from "antd";
import { CloudUploadOutlined } from "@ant-design/icons";
import { StatusLabel } from "@/components/StatusLabel";
import { EmptyState } from "@/components/shared/EmptyState";
import { formatTime } from "@/lib/format-time";
import { shortId, type DataSource, type IngestBatch } from "@/lib/api";

const SOURCE_TYPE_ICON: Record<string, string> = {
  file_upload: "📤",
  nas: "📡",
  crawler: "🕷",
  database: "🗄",
  webhook: "⚡",
};

interface BatchListProps {
  batches: IngestBatch[];
  dataSourceById: Record<string, DataSource | undefined>;
}

export function BatchList({ batches, dataSourceById }: BatchListProps) {
  if (batches.length === 0) {
    return (
      <EmptyState
        size="small"
        icon={<CloudUploadOutlined />}
        title="暂无接入活动"
        hint="从顶栏「快速上传」或注册数据源开始首次接入"
        actions={[{ label: "查看数据源", href: "/data-sources", type: "default" }]}
      />
    );
  }

  return (
    <div className="grid">
      {batches.map((b, idx) => {
        const ds = dataSourceById[b.data_source_id];
        const { display, iso } = formatTime(b.updated_at);
        const filename =
          (b.summary.filename as string | undefined) ??
          (b.summary.package_type as string | undefined) ??
          "—";
        const dsHref = ds ? `/data-sources/${ds.id}?tab=history` : "/data-sources";
        const isLast = idx === batches.length - 1;

        return (
          <Link
            key={b.id}
            href={dsHref}
            className={`hover:bg-bg-alt -mx-2 grid grid-cols-[24px_1fr_auto] items-center gap-2 px-2 py-2 text-inherit no-underline ${
              isLast ? "" : "border-line-light border-b"
            }`}
          >
            <span className="text-base">{SOURCE_TYPE_ICON[b.source_type] ?? "◎"}</span>
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm">
                <span className="truncate font-medium">{filename}</span>
                <Tooltip title={`批次 ID: ${b.id}`}>
                  <code className="text-text-muted font-mono text-xs">{shortId(b.id)}</code>
                </Tooltip>
              </div>
              <div className="text-text-secondary mt-0.5 truncate text-xs">
                {ds ? (
                  <>
                    <span>{ds.name}</span>
                    <Tag className="ml-2" color="default">
                      {ds.source_type}
                    </Tag>
                  </>
                ) : (
                  <span className="text-text-muted">数据源已删除</span>
                )}
              </div>
            </div>
            <div className="flex flex-col items-end gap-1">
              <StatusLabel value={b.status} />
              <time dateTime={iso} title={iso} className="text-text-muted text-xs">
                {display}
              </time>
            </div>
          </Link>
        );
      })}
    </div>
  );
}
