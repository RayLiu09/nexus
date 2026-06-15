"use client";

import { useCallback, useMemo, useState } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { App, Input, Select, Space, Table, Tag, Tooltip } from "antd";
import { CopyOutlined, SearchOutlined } from "@ant-design/icons";
import type { ColumnsType, TablePaginationConfig } from "antd/es/table";
import type { FilterValue, SorterResult } from "antd/es/table/interface";
import { shortId, type RawObject } from "@/lib/api";
import { StatusLabel } from "@/components/StatusLabel";
import { EmptyState } from "@/components/shared/EmptyState";
import { ApiState } from "@/components/ApiState";
import { formatTime } from "@/lib/format-time";
import { DEFAULT_PAGE_SIZE } from "@/lib/pagination";

interface RawLedgerContentProps {
  objects: RawObject[];
  totalCount: number;
  currentPage: number;
  pageSize: number;
  ok: boolean;
  error: string | null;
  traceId: string | null;
  dataSourceNames: Map<string, string>;
  filterBatchId?: string;
  filterDataSourceId?: string;
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

function extractFilename(obj: RawObject): string {
  const metaName = obj.metadata_summary?.filename;
  if (typeof metaName === "string" && metaName.length > 0) return metaName;
  // Fallback: last path segment of source_uri or object_uri
  const uri = obj.source_uri || obj.object_uri;
  if (uri) {
    const last = uri.split("/").pop();
    if (last && last.length > 0) return last;
  }
  return "-";
}

function CopyId({ id }: { id: string }) {
  const { message } = App.useApp();

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(id);
      message.success("已复制到剪贴板");
    } catch {
      message.error("复制失败，请手动复制");
    }
  };

  return (
    <span className="inline-flex items-center gap-1">
      <code className="text-xs" style={{ fontFamily: "var(--font-mono)" }}>
        {shortId(id)}
      </code>
      <Tooltip title="复制完整 ID">
        <CopyOutlined
          className="cursor-pointer text-[var(--text-muted)] hover:text-[var(--brand)]"
          onClick={handleCopy}
          style={{ fontSize: 12 }}
        />
      </Tooltip>
    </span>
  );
}

export function RawLedgerContent({
  objects,
  totalCount,
  currentPage,
  pageSize,
  ok,
  error,
  traceId,
  dataSourceNames,
  filterBatchId,
  filterDataSourceId,
}: RawLedgerContentProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const buildUrl = useCallback(
    (overrides: Record<string, string | undefined>) => {
      const params = new URLSearchParams(searchParams.toString());
      for (const [k, v] of Object.entries(overrides)) {
        if (v) {
          params.set(k, v);
        } else {
          params.delete(k);
        }
      }
      const qs = params.toString();
      return qs ? `${pathname}?${qs}` : pathname;
    },
    [pathname, searchParams],
  );

  const handleTableChange = useCallback(
    (
      pagination: TablePaginationConfig,
      _filters: Record<string, FilterValue | null>,
      _sorter: SorterResult<RawObject> | SorterResult<RawObject>[],
    ) => {
      const overrides: Record<string, string | undefined> = {};
      if (pagination.current && pagination.current > 1) {
        overrides.page = String(pagination.current);
      } else {
        overrides.page = undefined;
      }
      if (pagination.pageSize && pagination.pageSize !== DEFAULT_PAGE_SIZE) {
        overrides.pageSize = String(pagination.pageSize);
      } else {
        overrides.pageSize = undefined;
      }
      router.replace(buildUrl(overrides));
    },
    [router, buildUrl],
  );

  const [batchInput, setBatchInput] = useState(filterBatchId ?? "");

  const applyBatchFilter = useCallback(
    (value: string) => {
      router.replace(buildUrl({ batch_id: value || undefined, page: undefined }));
    },
    [router, buildUrl],
  );

  const handleDataSourceFilter = useCallback(
    (value: string | undefined) => {
      router.replace(buildUrl({ data_source_id: value || undefined, page: undefined }));
    },
    [router, buildUrl],
  );

  const dataSourceOptions = useMemo(
    () =>
      Array.from(dataSourceNames.entries())
        .map(([id, name]) => ({ value: id, label: name }))
        .sort((a, b) => a.label.localeCompare(b.label, "zh-CN")),
    [dataSourceNames],
  );

  const columns: ColumnsType<RawObject> = [
    {
      title: "对象 ID",
      dataIndex: "id",
      width: 160,
      fixed: "left",
      render: (id: string) => <CopyId id={id} />,
    },
    {
      title: "批次号",
      dataIndex: "batch_id",
      width: 160,
      render: (id: string) => <CopyId id={id} />,
    },
    {
      title: "数据源",
      dataIndex: "data_source_id",
      width: 140,
      render: (id: string) => (
        <span className="text-[var(--text-secondary)]">{dataSourceNames.get(id) ?? shortId(id)}</span>
      ),
    },
    {
      title: "文件名",
      dataIndex: "object_uri",
      width: 220,
      ellipsis: true,
      render: (_uri: string, record: RawObject) => {
        const name = extractFilename(record);
        const uri = record.source_uri || record.object_uri;
        return (
          <Tooltip title={uri}>
            <span className="text-[var(--text-secondary)]">{name}</span>
          </Tooltip>
        );
      },
    },
    {
      title: "类型",
      dataIndex: "mime_type",
      width: 80,
      render: (mime: string | null) => <Tag>{mimeLabel(mime)}</Tag>,
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
      render: (t: string) => {
        const ft = formatTime(t);
        return (
          <time dateTime={ft.iso} title={ft.iso} style={{ fontSize: 12, color: "var(--text-muted)" }}>
            {ft.display}
          </time>
        );
      },
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

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <Space>
          <Input
            placeholder="输入批次号，回车过滤"
            prefix={<SearchOutlined className="text-[var(--text-muted)]" />}
            value={batchInput}
            onChange={(e) => setBatchInput(e.target.value)}
            onPressEnter={() => applyBatchFilter(batchInput)}
            onBlur={() => applyBatchFilter(batchInput)}
            allowClear
            onClear={() => applyBatchFilter("")}
            style={{ width: 260 }}
          />
          <Select
            placeholder="按数据源过滤"
            value={filterDataSourceId ?? undefined}
            onChange={handleDataSourceFilter}
            allowClear
            showSearch
            optionFilterProp="label"
            options={dataSourceOptions}
            style={{ width: 220 }}
          />
          {(filterBatchId || filterDataSourceId) && (
            <span className="text-xs text-[var(--text-muted)]">
              当前过滤 {totalCount} 条结果
            </span>
          )}
        </Space>
      </div>

      {objects.length === 0 && !(filterBatchId || filterDataSourceId) ? (
        <EmptyState title="暂无原始对象" hint="数据接入提交后将在此展示原始数据对象" />
      ) : (
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
        />
      )}
    </>
  );
}
