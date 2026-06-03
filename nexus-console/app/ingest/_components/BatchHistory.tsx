"use client";

import Link from "next/link";
import { Card, Empty, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { StatusLabel } from "@/components/StatusLabel";
import { formatTime } from "@/lib/format-time";
import { shortId, type IngestBatch } from "@/lib/api";

const SOURCE_TYPE_LABELS: Record<string, string> = {
  file_upload: "本地文件上传",
  nas: "NAS 同步",
  crawler: "Crawler 爬虫",
  database: "数据库对接",
  webhook: "API 推送",
};

const BATCH_COLUMNS: ColumnsType<IngestBatch> = [
  {
    title: "文件名",
    key: "filename",
    ellipsis: true,
    render: (_: unknown, r: IngestBatch) => (
      <span className="font-medium">
        {String(r.summary.filename ?? r.summary.package_type ?? "-")}
      </span>
    ),
  },
  {
    title: "ID",
    dataIndex: "id",
    width: 140,
    render: (id: string) => <code className="font-mono text-caption text-muted">{shortId(id)}</code>,
  },
  {
    title: "来源类型",
    dataIndex: "source_type",
    width: 120,
    render: (t: string) => <Tag>{SOURCE_TYPE_LABELS[t] ?? t}</Tag>,
  },
  {
    title: "状态",
    dataIndex: "status",
    width: 100,
    render: (s: string) => <StatusLabel value={s} />,
  },
  {
    title: "更新时间",
    dataIndex: "updated_at",
    width: 150,
    render: (t: string) => {
      const { display, iso } = formatTime(t);
      return (
        <time dateTime={iso} title={iso} className="text-xs text-muted">
          {display}
        </time>
      );
    },
  },
];

export function BatchHistory({ batches }: { batches: IngestBatch[] }) {
  return (
    <Card
      title={
        <span>
          批次历史 <span className="text-xs text-muted font-normal ml-1">{batches.length} 个批次</span>
        </span>
      }
      extra={
        <Link href="/raw-ledger" className="text-xs text-brand hover:text-brand-strong">
          原始数据台账
        </Link>
      }
    >
      {batches.length === 0 ? (
        <div className="py-8">
          <Empty description="提交第一个数据批次后将在此显示处理历史" />
        </div>
      ) : (
        <Table<IngestBatch>
          rowKey="id"
          dataSource={batches}
          columns={BATCH_COLUMNS}
          size="middle"
          pagination={false}
        />
      )}
    </Card>
  );
}
