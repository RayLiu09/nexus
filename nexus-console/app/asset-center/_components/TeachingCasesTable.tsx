"use client";

import { useState, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { App, Button, Drawer, Space, Table, Tag, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import { BookOpen, Download, FileText } from "lucide-react";

import { ApiState } from "@/components/ApiState";
import type { TeachingCase } from "@/lib/api";
import { documentTagQuery, type DocumentTagFilters } from "@/lib/asset-center/document-filters";
import { DocumentTagSearch } from "./DocumentTagSearch";
import type { RawDownloadResponse } from "@/lib/chunkTypes";
import { ChunkListSection } from "@/app/assets/[assetId]/_components/ChunkListSection";
import { SourcePreviewSection } from "@/app/assets/[assetId]/_components/SourcePreviewSection";

type Props = {
  filters?: DocumentTagFilters;
  rows: TeachingCase[];
  total: number;
  page: number;
  pageSize: number;
  ok: boolean;
  error: string | null;
  traceId: string | null;
};

export function TeachingCasesTable({ filters = {}, rows, total, page, pageSize, ok, error, traceId }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const { message } = App.useApp();
  const [pending, startTransition] = useTransition();
  const [drawer, setDrawer] = useState<{ row: TeachingCase; view: "preview" | "chunks" } | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  function navigate(values: DocumentTagFilters, nextPage = 1, nextPageSize = pageSize) {
    const search = new URLSearchParams(documentTagQuery(values));
    if (nextPage > 1) search.set("page", String(nextPage));
    if (nextPageSize !== 20) search.set("pageSize", String(nextPageSize));
    startTransition(() => router.replace(`${pathname}${search.size ? `?${search}` : ""}`));
  }

  async function download(row: TeachingCase) {
    if (!row.raw_object_id) return;
    setDownloadingId(row.id);
    try {
      const response = await fetch(`/api/raw-objects/${encodeURIComponent(row.raw_object_id)}/download-url`, {
        cache: "no-store",
      });
      const body = (await response.json()) as
        | { ok: true; data: RawDownloadResponse }
        | { ok: false; message?: string };
      if (!body.ok) throw new Error(body.message ?? "原文下载失败");
      window.open(body.data.download_url, "_blank", "noopener,noreferrer");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "原文下载失败");
    } finally {
      setDownloadingId(null);
    }
  }

  const columns: ColumnsType<TeachingCase> = [
    { title: "资产名称", dataIndex: "asset_name", key: "name", width: "35%", ellipsis: true },
    {
      title: "内容标签", dataIndex: "content_tags", key: "tags", width: "35%",
      render: (values: string[]) => values?.length ? (
        <span>
          {values.slice(0, 3).map((value) => <Tag key={value}>{value}</Tag>)}
          {values.length > 3 && <Tooltip title={values.join("，")}><Tag>+{values.length - 3}</Tag></Tooltip>}
        </span>
      ) : "-",
    },
    {
      title: "操作", key: "actions", width: "30%",
      render: (_, row) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<FileText size={14} />}
            disabled={!row.normalized_ref_id} onClick={() => setDrawer({ row, view: "preview" })}>
            解析预览
          </Button>
          <Button type="link" size="small" icon={<BookOpen size={14} />}
            disabled={!row.normalized_ref_id} onClick={() => setDrawer({ row, view: "chunks" })}>
            RAG知识块
          </Button>
          <Button type="link" size="small" icon={<Download size={14} />}
            disabled={!row.raw_object_id} loading={downloadingId === row.id}
            onClick={() => void download(row)}>
            原文下载
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <>
      <ApiState ok={ok} error={error} traceId={traceId} />
      <div className="mb-3 flex flex-wrap justify-end">
        <DocumentTagSearch key={JSON.stringify(filters)} filters={filters} pending={pending}
          onSearch={(values) => navigate(values)} />
      </div>
      <Table<TeachingCase>
        rowKey="id" columns={columns} dataSource={rows} loading={pending}
        scroll={{ x: 1080 }} locale={{ emptyText: ok ? "暂无教学案例" : "暂无数据" }}
        pagination={{
          current: page, pageSize, total, showSizeChanger: true,
          showTotal: (value) => `共 ${value} 条`,
          onChange: (nextPage, nextPageSize) => navigate(filters, nextPage, nextPageSize),
        }}
      />
      <Drawer
        open={drawer !== null} onClose={() => setDrawer(null)} destroyOnHidden
        size="min(960px, calc(100vw - 32px))"
        title={drawer ? `${drawer.view === "preview" ? "解析预览" : "RAG知识块"} · ${drawer.row.asset_name}` : undefined}
      >
        {drawer?.view === "preview" && <SourcePreviewSection refId={drawer.row.normalized_ref_id} />}
        {drawer?.view === "chunks" && <ChunkListSection
          refId={drawer.row.normalized_ref_id} title="RAG知识块" mode="preview"
          actionLabel="预览定位" knowledgeTypeCode="teaching_case" />}
      </Drawer>
    </>
  );
}
