"use client";

import { useState, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { App, Button, Drawer, Space, Table, Tag, Tooltip } from "antd";
import type { ColumnsType, TablePaginationConfig } from "antd/es/table";
import { BookOpen, Download, FileText } from "lucide-react";
import type { RawDownloadResponse } from "@/lib/chunkTypes";

import { ApiState } from "@/components/ApiState";
import { documentTagQuery, type DocumentTagFilters } from "@/lib/asset-center/document-filters";
import { DocumentTagSearch } from "./DocumentTagSearch";
import type { IndustryPolicy } from "@/lib/api";
import { ChunkListSection } from "@/app/assets/[assetId]/_components/ChunkListSection";
import { SourcePreviewSection } from "@/app/assets/[assetId]/_components/SourcePreviewSection";

type Props = {
  rows: IndustryPolicy[];
  total: number;
  page: number;
  pageSize: number;
  ok: boolean;
  error: string | null;
  traceId: string | null;
  showRegion?: boolean;
  emptyText?: string;
  nameColumnTitle?: string;
  topic?: "finance_commerce" | "low_altitude";
  filters?: DocumentTagFilters;
  allCount: number | null;
  topicCounts: { finance_commerce: number | null; low_altitude: number | null };
};

type DrawerView = "chunks" | "preview";

function tags(values: string[], color?: string) {
  if (!values.length) return <span className="text-text-muted">-</span>;
  return (
    <span>
      {values.slice(0, 3).map((value) => (
        <Tag color={color} key={value}>
          {value}
        </Tag>
      ))}
      {values.length > 3 && (
        <Tooltip title={values.join("，")}>
          <Tag>+{values.length - 3}</Tag>
        </Tooltip>
      )}
    </span>
  );
}

export function IndustryPoliciesTable({
  rows,
  total,
  page,
  pageSize,
  ok,
  error,
  traceId,
  showRegion = true,
  emptyText = "暂无产教政策",
  nameColumnTitle = "资产名称",
  topic,
  filters = {},
  allCount,
  topicCounts,
}: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const [pending, startTransition] = useTransition();
  const [drawer, setDrawer] = useState<{ view: DrawerView; row: IndustryPolicy } | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const { message } = App.useApp();

  const downloadOriginal = async (row: IndustryPolicy) => {
    if (!row.raw_object_id) return;
    setDownloadingId(row.id);
    try {
      const response = await fetch(
        `/api/raw-objects/${encodeURIComponent(row.raw_object_id)}/download-url`,
        { cache: "no-store" },
      );
      const body = (await response.json()) as
        | { ok: true; data: RawDownloadResponse }
        | { ok: false; message?: string };
      if (!body.ok) throw new Error(body.message ?? `下载地址生成失败（HTTP ${response.status}）`);
      window.open(body.data.download_url, "_blank", "noopener,noreferrer");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "原文下载失败");
    } finally {
      setDownloadingId(null);
    }
  };

  const replacePage = (nextPage: number, nextPageSize: number) => {
    const search = new URLSearchParams(documentTagQuery(filters));
    if (topic) search.set("topic", topic);
    if (nextPage > 1) search.set("page", String(nextPage));
    if (nextPageSize !== 20) search.set("pageSize", String(nextPageSize));
    startTransition(() => router.replace(`${pathname}${search.size ? `?${search}` : ""}`));
  };

  const replaceTopic = (value: string) => {
    const search = new URLSearchParams(documentTagQuery(filters));
    if (value !== "all") search.set("topic", value);
    if (pageSize !== 20) search.set("pageSize", String(pageSize));
    startTransition(() => router.replace(`${pathname}${search.size ? `?${search}` : ""}`));
  };

  const topicOptions = [
    {
      value: "all",
      label: "全部",
      count: allCount,
      color: "border-neutral-300 border-b-neutral-400 bg-neutral-50 text-neutral-800",
      active: "ring-neutral-400",
      badge: "bg-neutral-200/80 text-neutral-800",
    },
    {
      value: "finance_commerce",
      label: "财经商贸类",
      count: topicCounts.finance_commerce,
      color: "border-emerald-300 border-b-emerald-500 bg-emerald-50 text-emerald-900",
      active: "ring-emerald-400",
      badge: "bg-emerald-200/70 text-emerald-950",
    },
    {
      value: "low_altitude",
      label: "低空经济类",
      count: topicCounts.low_altitude,
      color: "border-amber-300 border-b-amber-500 bg-amber-50 text-amber-950",
      active: "ring-amber-400",
      badge: "bg-amber-200/70 text-amber-950",
    },
  ];

  const columns: ColumnsType<IndustryPolicy> = [
    {
      title: nameColumnTitle,
      dataIndex: "asset_name",
      width: 280,
      fixed: "left",
      render: (value: string) => (
        <span className="text-text text-[15px] leading-6 font-semibold">{value || "-"}</span>
      ),
    },
    ...(showRegion
      ? [
          {
            title: "区域信息",
            dataIndex: "region",
            width: 180,
            render: (value: string[]) => tags(value, "blue"),
          },
        ]
      : []),
    {
      title: "行业领域",
      dataIndex: "industry",
      width: 200,
      render: (value: string[]) => tags(value, "green"),
    },
    {
      title: "发布时间",
      dataIndex: "publish_date",
      width: 130,
      render: (value: string | null) => value || "-",
    },
    {
      title: "内容标签",
      dataIndex: "content_tags",
      width: 260,
      render: (value: string[]) => tags(value),
    },
    {
      title: "操作",
      key: "actions",
      width: 230,
      fixed: "right",
      render: (_, row) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            icon={<BookOpen size={14} />}
            disabled={!row.normalized_ref_id}
            onClick={() => setDrawer({ view: "chunks", row })}
          >
            知识块视图
          </Button>
          <Button
            type="link"
            size="small"
            icon={<FileText size={14} />}
            disabled={!row.normalized_ref_id}
            onClick={() => setDrawer({ view: "preview", row })}
          >
            解析预览
          </Button>
          <Button
            type="link"
            size="small"
            icon={<Download size={14} />}
            loading={downloadingId === row.id}
            disabled={!row.raw_object_id}
            onClick={() => void downloadOriginal(row)}
          >
            原文下载
          </Button>
        </Space>
      ),
    },
  ];

  const pagination: TablePaginationConfig = {
    current: page,
    pageSize,
    total,
    showSizeChanger: true,
    showTotal: (value) => `共 ${value} 条`,
    onChange: (nextPage, nextPageSize) => replacePage(nextPage, nextPageSize),
  };

  return (
    <>
      <div className="flex flex-col gap-4">
        <ApiState ok={ok} error={error} traceId={traceId} />
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex flex-wrap gap-3 pb-1" role="group" aria-label="主题分类">
            {topicOptions.map((option) => (
              <button
                key={option.value}
                type="button"
                aria-label={`${option.label} ${option.count ?? "-"}`}
                aria-pressed={(topic ?? "all") === option.value}
                onClick={() => replaceTopic(option.value)}
                className={`inline-flex min-h-10 items-center gap-2.5 rounded-md border border-b-2 px-3.5 py-2 text-sm font-semibold shadow-[0_3px_8px_rgba(15,20,36,0.10),inset_0_1px_0_rgba(255,255,255,0.85)] transition-[transform,box-shadow,filter] duration-150 hover:-translate-y-0.5 hover:shadow-[0_5px_12px_rgba(15,20,36,0.14),inset_0_1px_0_rgba(255,255,255,0.9)] focus-visible:outline-2 focus-visible:outline-offset-2 active:translate-y-0 active:shadow-[inset_0_1px_3px_rgba(15,20,36,0.12)] ${option.color} ${(topic ?? "all") === option.value ? `ring-2 ring-offset-1 ${option.active}` : ""}`}
              >
                <span>{option.label}</span>
                <span
                  className={`min-w-7 rounded px-1.5 py-0.5 text-center text-sm font-bold tabular-nums ${option.badge}`}
                >
                  {option.count ?? "-"}
                </span>
              </button>
            ))}
          </div>
          <DocumentTagSearch
            key={JSON.stringify(filters)}
            filters={filters}
            pending={pending}
            onSearch={(values) => {
              const search = new URLSearchParams(documentTagQuery(values));
              if (topic) search.set("topic", topic);
              if (pageSize !== 20) search.set("pageSize", String(pageSize));
              startTransition(() =>
                router.replace(`${pathname}${search.size ? `?${search}` : ""}`),
              );
            }}
          />
        </div>
        <Table<IndustryPolicy>
          rowKey="id"
          columns={columns}
          dataSource={rows}
          loading={pending}
          pagination={pagination}
          scroll={{ x: 1280 }}
          locale={{ emptyText: ok ? emptyText : "暂无数据" }}
        />
      </div>
      <Drawer
        open={drawer !== null}
        onClose={() => setDrawer(null)}
        size="min(960px, calc(100vw - 32px))"
        title={
          drawer
            ? `${drawer.view === "chunks" ? "知识块视图" : "解析预览"} · ${drawer.row.asset_name}`
            : undefined
        }
        destroyOnHidden
      >
        {drawer?.view === "chunks" && drawer.row.normalized_ref_id && (
          <ChunkListSection
            refId={drawer.row.normalized_ref_id}
            title="RAG知识块"
            mode="preview"
            actionLabel="预览定位"
          />
        )}
        {drawer?.view === "preview" && (
          <SourcePreviewSection refId={drawer?.row.normalized_ref_id ?? null} />
        )}
      </Drawer>
    </>
  );
}
