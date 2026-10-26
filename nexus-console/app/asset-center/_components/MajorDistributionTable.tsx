"use client";

import { useEffect, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Button, Form, Input, Space, Table } from "antd";
import type { ColumnsType, TablePaginationConfig } from "antd/es/table";
import { Download, Search, X } from "lucide-react";

import { ApiState } from "@/components/ApiState";
import type { MajorOfferingRecord } from "@/lib/api";

export type MajorDistributionFilters = {
  year?: string;
  province_name?: string;
  major_name?: string;
  major_code?: string;
  school_name?: string;
};

type Props = {
  rows: MajorOfferingRecord[];
  total: number;
  page: number;
  pageSize: number;
  filters: MajorDistributionFilters;
  ok: boolean;
  error: string | null;
  traceId: string | null;
};

const filterFields = [
  ["year", "年份"], ["province_name", "省份"], ["major_code", "专业代码"],
  ["major_name", "专业名称"], ["school_name", "学校名称"],
] as const;
const emptyFilters = Object.fromEntries(filterFields.map(([key]) => [key, undefined]));

export function MajorDistributionTable({ rows, total, page, pageSize, filters, ok, error, traceId }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const [pending, startTransition] = useTransition();
  const [filterForm] = Form.useForm<MajorDistributionFilters>();
  useEffect(() => filterForm.setFieldsValue({ ...emptyFilters, ...filters }), [filterForm, filters]);
  const exportSearch = new URLSearchParams();
  for (const [key] of filterFields) {
    const value = filters[key]?.trim();
    if (value) exportSearch.set(key, value);
  }
  const exportUrl = `/api/asset-center/major-offerings/export${exportSearch.size ? `?${exportSearch}` : ""}`;

  const replaceQuery = (next: MajorDistributionFilters, nextPage = 1, nextSize = pageSize) => {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(next)) {
      if (value?.trim()) search.set(key, value.trim());
    }
    if (nextPage > 1) search.set("page", String(nextPage));
    if (nextSize !== 20) search.set("pageSize", String(nextSize));
    startTransition(() => router.replace(`${pathname}${search.size ? `?${search}` : ""}`));
  };
  const columns: ColumnsType<MajorOfferingRecord> = [
    { title: "年份", dataIndex: "year", width: 88 },
    { title: "省份", dataIndex: "province_name", width: 120 },
    { title: "专业代码", dataIndex: "major_code", width: 118 },
    { title: "专业名称", dataIndex: "major_name", width: 180 },
    { title: "学校标识码", dataIndex: "school_code", width: 150, render: (v) => v || "-" },
    { title: "学校名称", dataIndex: "school_name", width: 220 },
    { title: "年限", dataIndex: "study_duration", width: 88 },
    { title: "备注", dataIndex: "remark", width: 220, render: (v) => v || "-" },
  ];
  const handleTableChange = (pagination: TablePaginationConfig) =>
    replaceQuery(filters, pagination.current ?? 1, pagination.pageSize ?? pageSize);

  return (
    <>
      <ApiState ok={ok} error={error} traceId={traceId} />
      <section className="border-line bg-surface border-y">
        <Form form={filterForm} layout="inline" initialValues={filters}
          className="border-line flex flex-wrap justify-end gap-2 border-b px-4 py-3"
          onFinish={(values) => replaceQuery(values)}>
          {filterFields.map(([key, title]) => (
            <Form.Item key={key} name={key} className="!mb-0">
              <Input allowClear placeholder={title} aria-label={title} className="w-32" />
            </Form.Item>
          ))}
          <Form.Item className="!mb-0">
            <Space size={8}>
              <Button htmlType="submit" type="primary" icon={<Search size={15} />}>检索</Button>
              <Button icon={<X size={15} />} onClick={() => {
                filterForm.setFieldsValue(emptyFilters);
                replaceQuery({});
              }}>重置</Button>
              <Button icon={<Download size={15} />} href={exportUrl} target="_blank">导出 Excel</Button>
            </Space>
          </Form.Item>
        </Form>
        <Table<MajorOfferingRecord> rowKey="id" size="small" columns={columns} dataSource={rows}
          loading={pending} scroll={{ x: 1184 }}
          pagination={{ current: page, pageSize, total, showSizeChanger: true, showTotal: (count) => `共 ${count} 条` }}
          locale={{ emptyText: ok ? "暂无专业布点记录" : "数据加载失败" }} onChange={handleTableChange} />
      </section>
    </>
  );
}
