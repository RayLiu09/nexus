"use client";

import { useEffect, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Button, Form, Input, Space, Table } from "antd";
import type { ColumnsType, TablePaginationConfig } from "antd/es/table";
import { Search, X } from "lucide-react";

import { ApiState } from "@/components/ApiState";
import type { OccupationDictionaryRecord } from "@/lib/api";
import { DEFAULT_PAGE_SIZE } from "@/lib/pagination";

export type OccupationDictionaryFilters = {
  major_group?: string;
  minor_group?: string;
  occupation_name?: string;
};

type Props = {
  rows: OccupationDictionaryRecord[];
  total: number;
  page: number;
  pageSize: number;
  filters: OccupationDictionaryFilters;
  ok: boolean;
  error: string | null;
  traceId: string | null;
};
const filterFields = [
  ["major_group", "职业大类"],
  ["minor_group", "职业小类"],
  ["occupation_name", "职业名称"],
] as const;
const emptyFilters = { major_group: undefined, minor_group: undefined, occupation_name: undefined };
const paragraph = (value: string | null) => (
  <div className="break-words whitespace-pre-wrap">{value || "未提供"}</div>
);
const columns: ColumnsType<OccupationDictionaryRecord> = [
  { title: "职业类别", dataIndex: "occupation_category", width: 220, render: paragraph },
  { title: "职业大类", dataIndex: "major_group", width: 220, render: paragraph },
  { title: "职业小类", dataIndex: "minor_group", width: 220, render: paragraph },
  {
    title: "职业名称",
    dataIndex: "occupation_name",
    width: 180,
    render: (value, row) => (
      <div>
        <div>{value}</div>
        <div className="text-muted mt-1 text-xs">{row.occupation_code}</div>
      </div>
    ),
  },
  { title: "职业定义", dataIndex: "definition", width: 320, render: paragraph },
  { title: "工作任务", dataIndex: "work_tasks", width: 480, render: paragraph },
];

export function OccupationDictionaryTable({
  rows,
  total,
  page,
  pageSize,
  filters,
  ok,
  error,
  traceId,
}: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const [pending, startTransition] = useTransition();
  const [form] = Form.useForm<OccupationDictionaryFilters>();
  useEffect(() => form.setFieldsValue({ ...emptyFilters, ...filters }), [form, filters]);
  const replaceQuery = (next: OccupationDictionaryFilters, nextPage = 1, nextSize = pageSize) => {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(next)) {
      if (value?.trim()) query.set(key, value.trim());
    }
    if (nextPage > 1) query.set("page", String(nextPage));
    if (nextSize !== DEFAULT_PAGE_SIZE) query.set("pageSize", String(nextSize));
    startTransition(() => router.replace(`${pathname}${query.size ? `?${query}` : ""}`));
  };
  const onChange = (pagination: TablePaginationConfig) =>
    replaceQuery(
      filters,
      pagination.pageSize !== pageSize ? 1 : (pagination.current ?? 1),
      pagination.pageSize ?? pageSize,
    );

  return (
    <>
      <ApiState ok={ok} error={error} traceId={traceId} />
      <p className="text-muted mb-3 text-sm">
        来源：《中华人民共和国职业分类大典（2022年版）》职业名录及所提供原文。
      </p>
      <section className="border-line bg-surface border-y">
        <Form
          form={form}
          layout="inline"
          initialValues={filters}
          className="border-line flex flex-wrap justify-end gap-2 border-b px-4 py-3"
          onFinish={(values) => replaceQuery(values)}
        >
          {filterFields.map(([key, title]) => (
            <Form.Item key={key} name={key} className="!mb-0">
              <Input allowClear placeholder={title} aria-label={title} className="w-44" />
            </Form.Item>
          ))}
          <Form.Item className="!mb-0">
            <Space size={8}>
              <Button htmlType="submit" type="primary" icon={<Search size={15} />}>
                检索
              </Button>
              <Button
                icon={<X size={15} />}
                onClick={() => {
                  form.setFieldsValue(emptyFilters);
                  replaceQuery({});
                }}
              >
                重置
              </Button>
            </Space>
          </Form.Item>
        </Form>
        <Table<OccupationDictionaryRecord>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={rows}
          loading={pending}
          scroll={{ x: 1640 }}
          onChange={onChange}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (count) => `共 ${count} 条`,
          }}
          locale={{ emptyText: ok ? "暂无匹配的职业记录" : "数据加载失败" }}
        />
      </section>
    </>
  );
}
