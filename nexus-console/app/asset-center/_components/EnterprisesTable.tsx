"use client";

import { useState, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Button, Input, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Download, Search, X } from "lucide-react";
import { ApiState } from "@/components/ApiState";
import type { Enterprise } from "@/lib/api";

type Props = {
  rows: Enterprise[];
  total: number;
  page: number;
  pageSize: number;
  q?: string;
  ok: boolean;
  error: string | null;
  traceId: string | null;
};
export function EnterprisesTable({ rows, total, page, pageSize, q, ok, error, traceId }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const [pending, startTransition] = useTransition();
  const [value, setValue] = useState(q ?? "");
  const replace = (nextPage = 1, nextPageSize = pageSize) => {
    const search = new URLSearchParams();
    if (value.trim()) search.set("q", value.trim());
    if (nextPage > 1) search.set("page", String(nextPage));
    if (nextPageSize !== 20) search.set("pageSize", String(nextPageSize));
    startTransition(() => router.replace(`${pathname}${search.size ? `?${search}` : ""}`));
  };
  const columns: ColumnsType<Enterprise> = [
    {
      title: "企业名称",
      dataIndex: "enterprise_name",
      width: 270,
      fixed: "left",
      render: (v) => <strong>{v}</strong>,
    },
    { title: "经营范围", dataIndex: "business_scope", width: 600, ellipsis: true },
    {
      title: "所属产业园区",
      dataIndex: "park_name",
      width: 240,
      render: (v) => v || <span className="text-text-muted">未关联</span>,
    },
  ];
  return (
    <>
      <ApiState ok={ok} error={error} traceId={traceId} />
      <section className="border-line bg-surface border-y">
        <div className="border-line flex flex-wrap items-center gap-2 border-b px-4 py-3">
          <Input
            placeholder="企业名称、经营范围或园区"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onPressEnter={() => replace()}
            className="w-72"
          />
          <Button type="primary" icon={<Search size={15} />} onClick={() => replace()}>
            查询
          </Button>
          <Button
            icon={<X size={15} />}
            onClick={() => {
              setValue("");
              startTransition(() => router.replace(pathname));
            }}
          >
            重置
          </Button>
          <Button
            icon={<Download size={15} />}
            href="/api/asset-center/enterprises/export"
            target="_blank"
          >
            导出 Excel
          </Button>
        </div>
        <Table<Enterprise>
          rowKey="id"
          columns={columns}
          dataSource={rows}
          loading={pending}
          scroll={{ x: 1200 }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (count) => `共 ${count} 条`,
            onChange: (next, size) => replace(next, size),
          }}
          locale={{ emptyText: ok ? "暂无企业数据" : "数据加载失败" }}
        />
      </section>
    </>
  );
}
