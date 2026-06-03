"use client";

import { Empty, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";

import type { BatchDetail, BatchSubmitItem } from "./batch.types";

interface FileStatusRow {
  key: string;
  fileKey: string;
  filename: string;
  rawObjectId: string;
  jobId: string;
  status: string;
  duplicate: boolean;
}

interface FileStatusListProps {
  submittedItems: BatchSubmitItem[];
  fileNamesByKey: Record<string, string>;
  batchDetail: BatchDetail | null;
}

const STATUS_TONE: Record<string, "default" | "success" | "warning" | "error" | "processing"> = {
  queued: "processing",
  running: "processing",
  succeeded: "success",
  failed: "error",
  dead_lettered: "error",
  cancelled: "warning",
  review_required: "warning",
};

function statusLabel(status: string): string {
  switch (status) {
    case "queued":
      return "排队中";
    case "running":
      return "处理中";
    case "succeeded":
      return "成功";
    case "failed":
      return "失败";
    case "dead_lettered":
      return "已死信";
    case "cancelled":
      return "已取消";
    case "review_required":
      return "待复核";
    default:
      return status;
  }
}

export function FileStatusList({
  submittedItems,
  fileNamesByKey,
  batchDetail,
}: FileStatusListProps) {
  if (submittedItems.length === 0) {
    return (
      <Empty
        description="提交批次后将在此实时展示每个文件的处理状态"
        image={Empty.PRESENTED_IMAGE_SIMPLE}
      />
    );
  }

  const detail = batchDetail?.batch_status_detail ?? {};

  const rows: FileStatusRow[] = submittedItems.map((item) => ({
    key: item.file_idempotency_key,
    fileKey: item.file_idempotency_key,
    filename: fileNamesByKey[item.file_idempotency_key] ?? item.file_idempotency_key,
    rawObjectId: item.raw_object_id,
    jobId: item.job_id,
    status: detail[item.raw_object_id] ?? item.job_status,
    duplicate: item.duplicate,
  }));

  const columns: ColumnsType<FileStatusRow> = [
    {
      title: "文件名",
      dataIndex: "filename",
      key: "filename",
      render: (value: string, record) => (
        <span className="flex items-center gap-2">
          <span className="font-medium">{value}</span>
          {record.duplicate && (
            <Tag color="default" className="ml-1">
              幂等复用
            </Tag>
          )}
        </span>
      ),
    },
    {
      title: "幂等键",
      dataIndex: "fileKey",
      key: "fileKey",
      render: (value: string) => <code className="font-mono text-xs text-text-muted">{value}</code>,
    },
    {
      title: "Job 状态",
      dataIndex: "status",
      key: "status",
      width: 140,
      render: (value: string) => {
        const tone = STATUS_TONE[value] ?? "default";
        return <Tag color={tone}>{statusLabel(value)}</Tag>;
      },
    },
    {
      title: "Job ID",
      dataIndex: "jobId",
      key: "jobId",
      render: (value: string) => (
        <code className="font-mono text-xs text-text-muted">{value.slice(0, 8)}…</code>
      ),
    },
  ];

  return (
    <Table<FileStatusRow>
      size="small"
      columns={columns}
      dataSource={rows}
      pagination={false}
      rowKey="key"
    />
  );
}
