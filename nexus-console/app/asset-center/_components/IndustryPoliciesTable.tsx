"use client";

import { useState, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Button, Drawer, Space, Table, Tag, Tooltip } from "antd";
import type { ColumnsType, TablePaginationConfig } from "antd/es/table";
import { BookOpen, FileText } from "lucide-react";

import { ApiState } from "@/components/ApiState";
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
}: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const [pending, startTransition] = useTransition();
  const [drawer, setDrawer] = useState<{ view: DrawerView; row: IndustryPolicy } | null>(null);

  const replacePage = (nextPage: number, nextPageSize: number) => {
    const search = new URLSearchParams();
    if (nextPage > 1) search.set("page", String(nextPage));
    if (nextPageSize !== 20) search.set("pageSize", String(nextPageSize));
    startTransition(() => router.replace(`${pathname}${search.size ? `?${search}` : ""}`));
  };

  const columns: ColumnsType<IndustryPolicy> = [
    {
      title: nameColumnTitle,
      dataIndex: "asset_name",
      width: 280,
      fixed: "left",
      render: (value: string) => <strong>{value || "-"}</strong>,
    },
    ...(showRegion
      ? [{
      title: "区域信息",
      dataIndex: "region",
      width: 180,
      render: (value: string[]) => tags(value, "blue"),
      }]
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
            原文预览
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
        width="min(960px, calc(100vw - 32px))"
        title={
          drawer
            ? `${drawer.view === "chunks" ? "知识块视图" : "原文预览"} · ${drawer.row.asset_name}`
            : undefined
        }
        destroyOnClose
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
