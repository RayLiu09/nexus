"use client";

import { useState, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Button, Input, Space, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Download, Search, X } from "lucide-react";
import { ApiState } from "@/components/ApiState";
import type { IndustrialPark } from "@/lib/api";

type Props = {
  rows: IndustrialPark[];
  total: number;
  page: number;
  pageSize: number;
  q?: string;
  industry?: string;
  ok: boolean;
  error: string | null;
  traceId: string | null;
};

export function IndustrialParksTable({
  rows,
  total,
  page,
  pageSize,
  q,
  industry,
  ok,
  error,
  traceId,
}: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const [pending, startTransition] = useTransition();
  const [filters, setFilters] = useState({ q: q ?? "", industry: industry ?? "" });
  const replace = (nextPage = 1, nextPageSize = pageSize) => {
    const search = new URLSearchParams();
    if (filters.q.trim()) search.set("q", filters.q.trim());
    if (filters.industry.trim()) search.set("industry", filters.industry.trim());
    if (nextPage > 1) search.set("page", String(nextPage));
    if (nextPageSize !== 20) search.set("pageSize", String(nextPageSize));
    startTransition(() => router.replace(`${pathname}${search.size ? `?${search}` : ""}`));
  };
  const columns: ColumnsType<IndustrialPark> = [
    {
      title: "园区名称",
      dataIndex: "park_name",
      width: 240,
      fixed: "left",
      render: (value) => <strong>{value}</strong>,
    },
    {
      title: "行业标签",
      dataIndex: "industry_tags",
      width: 180,
      render: (values: string[]) => (
        <Space wrap>
          {values.map((value) => (
            <Tag key={value} color="blue">
              {value}
            </Tag>
          ))}
        </Space>
      ),
    },
    { title: "园区介绍", dataIndex: "introduction", width: 520, ellipsis: true },
    { title: "企业数量", dataIndex: "enterprise_count", width: 110, align: "center" },
  ];
  return (
    <>
      <ApiState ok={ok} error={error} traceId={traceId} />
      <section className="border-line bg-surface border-y">
        <div className="border-line flex flex-wrap items-center gap-2 border-b px-4 py-3">
          <Input
            placeholder="园区名称或介绍"
            value={filters.q}
            onChange={(event) => setFilters((old) => ({ ...old, q: event.target.value }))}
            className="w-52"
          />
          <Input
            placeholder="行业标签"
            value={filters.industry}
            onChange={(event) => setFilters((old) => ({ ...old, industry: event.target.value }))}
            className="w-40"
          />
          <Button type="primary" icon={<Search size={15} />} onClick={() => replace()}>
            查询
          </Button>
          <Button
            icon={<X size={15} />}
            onClick={() => {
              setFilters({ q: "", industry: "" });
              startTransition(() => router.replace(pathname));
            }}
          >
            重置
          </Button>
          <Button
            icon={<Download size={15} />}
            href="/api/asset-center/industrial-parks/export"
            target="_blank"
          >
            导出 Excel
          </Button>
        </div>
        <Table<IndustrialPark>
          rowKey="id"
          columns={columns}
          dataSource={rows}
          loading={pending}
          scroll={{ x: 1100 }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (count) => `共 ${count} 条`,
            onChange: (next, size) => replace(next, size),
          }}
          locale={{ emptyText: ok ? "暂无产业园区数据" : "数据加载失败" }}
        />
      </section>
    </>
  );
}
