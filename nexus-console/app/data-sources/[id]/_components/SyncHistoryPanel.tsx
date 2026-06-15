"use client";

import { Table } from "antd";
import { HistoryOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import Link from "next/link";

import { EmptyState } from "@/components/shared/EmptyState";
import { StatusLabel } from "@/components/StatusLabel";
import { formatTime } from "@/lib/format-time";
import { shortId, type IngestBatch } from "@/lib/api";

interface SyncHistoryPanelProps {
  batches: IngestBatch[];
}

interface Row {
  key: string;
  filename: string;
  batchId: string;
  status: string;
  updatedAt: string;
}

export function SyncHistoryPanel({ batches }: SyncHistoryPanelProps) {
  if (batches.length === 0) {
    return (
      <EmptyState
        icon={<HistoryOutlined />}
        title="此数据源尚无接入批次"
        hint="批次提交或定时同步触发后会出现在这里"
      />
    );
  }

  const rows: Row[] = batches.map((b) => ({
    key: b.id,
    filename: String(b.summary.filename ?? b.summary.package_type ?? "—"),
    batchId: b.id,
    status: b.status,
    updatedAt: b.updated_at,
  }));

  const columns: ColumnsType<Row> = [
    {
      title: "文件 / 包",
      dataIndex: "filename",
      key: "filename",
      render: (v: string) => <span className="font-medium">{v}</span>,
    },
    {
      title: "批次 ID",
      dataIndex: "batchId",
      key: "batchId",
      width: 140,
      render: (v: string) => (
        <code className="text-text-muted font-mono text-xs">{shortId(v)}</code>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 120,
      render: (v: string) => <StatusLabel value={v} />,
    },
    {
      title: "更新时间",
      dataIndex: "updatedAt",
      key: "updatedAt",
      width: 180,
      render: (v: string) => {
        const t = formatTime(v);
        return (
          <time dateTime={t.iso} title={t.iso} className="text-text-muted text-xs">
            {t.display}
          </time>
        );
      },
    },
  ];

  return (
    <>
      <Table<Row>
        size="small"
        rowKey="key"
        columns={columns}
        dataSource={rows}
        pagination={{ pageSize: 20, hideOnSinglePage: true }}
      />
      <div className="mt-3 text-right">
        <Link href="/raw-ledger" className="text-brand text-xs">
          查看原始数据台账 →
        </Link>
      </div>
    </>
  );
}
