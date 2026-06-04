"use client";

import { useCallback } from "react";
import { useRouter, usePathname } from "next/navigation";
import { Table, Tag } from "antd";
import type { ColumnsType, TablePaginationConfig } from "antd/es/table";
import type { FilterValue, SorterResult } from "antd/es/table/interface";
import { formatDateTime, shortId, type RawObject } from "@/lib/api";
import { StatusLabel } from "@/components/StatusLabel";
import { ApiState } from "@/components/ApiState";
import { DEFAULT_PAGE_SIZE } from "@/lib/pagination";

interface RawLedgerContentProps {
  objects: RawObject[];
  totalCount: number;
  currentPage: number;
  pageSize: number;
  ok: boolean;
  error: string | null;
  traceId: string | null;
}

const MIME_LABELS: Record<string, string> = {
  "application/pdf": "PDF",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "XLSX",
  "text/plain": "TXT",
  "text/markdown": "MD",
  "text/html": "HTML",
  "text/csv": "CSV",
  "application/json": "JSON",
  "image/png": "PNG",
  "image/jpeg": "JPEG",
  "image/tiff": "TIFF",
};

function mimeLabel(mime: string | null): string {
  if (!mime) return "-";
  return MIME_LABELS[mime] ?? mime;
}

function formatSize(bytes: number | null): string {
  if (bytes == null) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function RawLedgerContent({
  objects,
  totalCount,
  currentPage,
  pageSize,
  ok,
  error,
  traceId,
}: RawLedgerContentProps) {
  const router = useRouter();
  const pathname = usePathname();

  const handleTableChange = useCallback(
    (
      pagination: TablePaginationConfig,
      _filters: Record<string, FilterValue | null>,
      _sorter: SorterResult<RawObject> | SorterResult<RawObject>[],
    ) => {
      const params = new URLSearchParams();
      if (pagination.current && pagination.current > 1) {
        params.set("page", String(pagination.current));
      }
      if (pagination.pageSize && pagination.pageSize !== DEFAULT_PAGE_SIZE) {
        params.set("pageSize", String(pagination.pageSize));
      }
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname);
    },
    [router, pathname],
  );

  const columns: ColumnsType<RawObject> = [
    {
      title: "对象 ID",
      dataIndex: "id",
      width: 140,
      fixed: "left",
      render: (id: string) => (
        <code style={{ fontSize: 11, fontFamily: "var(--font-mono)" }}>{shortId(id)}</code>
      ),
    },
    {
      title: "批次号",
      dataIndex: "batch_id",
      width: 140,
      render: (id: string) => (
        <code style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
          {shortId(id)}
        </code>
      ),
    },
    {
      title: "数据源",
      dataIndex: "data_source_id",
      width: 140,
      render: (id: string) => (
        <code style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
          {shortId(id)}
        </code>
      ),
    },
    {
      title: "类型",
      dataIndex: "mime_type",
      width: 80,
      render: (mime: string | null) => <Tag>{mimeLabel(mime)}</Tag>,
    },
    {
      title: "对象 URI",
      dataIndex: "object_uri",
      width: 280,
      ellipsis: true,
      render: (uri: string) => (
        <code style={{ fontSize: 12, fontFamily: "var(--font-mono)" }} title={uri}>
          {uri}
        </code>
      ),
    },
    {
      title: "大小",
      dataIndex: "size_bytes",
      width: 90,
      align: "right" as const,
      render: (size: number | null) => (
        <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>{formatSize(size)}</span>
      ),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 160,
      render: (t: string) => (
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{formatDateTime(t)}</span>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (s: string) => <StatusLabel value={s} />,
    },
  ];

  return (
    <>
      <ApiState ok={ok} error={error} traceId={traceId} />

      <Table
        rowKey="id"
        dataSource={objects}
        columns={columns}
        size="middle"
        pagination={{
          current: currentPage,
          pageSize,
          total: totalCount,
          showSizeChanger: true,
          showTotal: (total, range) => `${range[0]}-${range[1]} / ${total} 条记录`,
          pageSizeOptions: ["10", "20", "50"],
        }}
        onChange={handleTableChange}
        scroll={{ x: 1100 }}
        locale={{ emptyText: "暂无原始对象" }}
      />
    </>
  );
}
