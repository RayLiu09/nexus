"use client";

import { useEffect, useState, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { App, Button, Form, Input, Space, Table, Tooltip } from "antd";
import type { ColumnsType, TablePaginationConfig } from "antd/es/table";
import { Download, Search, X } from "lucide-react";

import { ApiState } from "@/components/ApiState";
import type { RawJob } from "@/lib/api";

export type JobDemandFilters = { q?: string; industry?: string };

type Props = {
  rows: RawJob[];
  total: number;
  page: number;
  pageSize: number;
  filters: JobDemandFilters;
  ok: boolean;
  error: string | null;
  traceId: string | null;
};

function cell(value: string | null, maxWidth = 220) {
  if (!value) return "-";
  return (
    <Tooltip title={value} placement="topLeft">
      <span className="block max-w-full truncate" style={{ maxWidth }}>
        {value}
      </span>
    </Tooltip>
  );
}

export function JobDemandTable({
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
  const [exporting, setExporting] = useState(false);
  const [form] = Form.useForm<JobDemandFilters>();
  const { message } = App.useApp();

  useEffect(() => form.setFieldsValue(filters), [filters, form]);

  const replaceQuery = (next: JobDemandFilters, nextPage = 1, nextPageSize = pageSize) => {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(next)) {
      if (value?.trim()) search.set(key, value.trim());
    }
    if (nextPage > 1) search.set("page", String(nextPage));
    if (nextPageSize !== 20) search.set("pageSize", String(nextPageSize));
    startTransition(() => router.replace(`${pathname}${search.size ? `?${search}` : ""}`));
  };

  const exportAll = async () => {
    const params = new URLSearchParams();
    if (filters.q?.trim()) params.set("q", filters.q.trim());
    if (filters.industry?.trim()) params.set("industry", filters.industry.trim());
    setExporting(true);
    try {
      const response = await fetch(`/api/raw-jobs/export${params.size ? `?${params}` : ""}`);
      if (!response.ok) {
        const body = await response.json().catch(() => ({})) as { error?: { message?: string } };
        throw new Error(body.error?.message ?? "岗位数据导出失败");
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `岗位数据-${new Date().toISOString().slice(0, 10)}.xlsx`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "岗位数据导出失败");
    } finally {
      setExporting(false);
    }
  };

  const columns: ColumnsType<RawJob> = [
    {
      title: "岗位名称",
      dataIndex: "job_title",
      width: 180,
      fixed: "left",
      render: (v) => <strong>{v}</strong>,
    },
    {
      title: "岗位职责要求",
      dataIndex: "job_responsibilities",
      width: 260,
      render: (v) => cell(v),
    },
    {
      title: "经验要求",
      dataIndex: "experience_requirement",
      width: 140,
      render: (v) => cell(v, 140),
    },
    { title: "学历", dataIndex: "education", width: 110, render: (v) => cell(v, 110) },
    { title: "薪资范围", dataIndex: "salary_range", width: 140, render: (v) => cell(v, 140) },
    { title: "所在行业", dataIndex: "industry", width: 160, render: (v) => cell(v, 160) },
    { title: "公司名称", dataIndex: "company_name", width: 190, render: (v) => cell(v, 190) },
    { title: "规模", dataIndex: "company_size", width: 120, render: (v) => cell(v, 120) },
    { title: "地址", dataIndex: "address", width: 220, render: (v) => cell(v) },
  ];

  const pagination: TablePaginationConfig = {
    current: page,
    pageSize,
    total,
    showSizeChanger: true,
    showTotal: (value) => `共 ${value} 条`,
    onChange: (nextPage, nextPageSize) => replaceQuery(filters, nextPage, nextPageSize),
  };

  return (
    <div className="flex flex-col gap-4">
      <Form
        layout="inline"
        form={form}
        className="flex w-full flex-wrap justify-end gap-2"
        onFinish={(values) => replaceQuery(values)}
      >
        <Form.Item name="q" label="关键词">
          <Input allowClear placeholder="岗位名称或公司名称" style={{ width: 240 }} />
        </Form.Item>
        <Form.Item name="industry" label="行业">
          <Input allowClear placeholder="所在行业" style={{ width: 180 }} />
        </Form.Item>
        <Space>
          <Button type="primary" htmlType="submit" icon={<Search size={15} />} loading={pending}>
            检索
          </Button>
          <Button
            icon={<X size={15} />}
            onClick={() => {
              form.resetFields();
              replaceQuery({});
            }}
          >
            重置
          </Button>
          <Button
            icon={<Download size={15} />}
            loading={exporting}
            disabled={!ok || total === 0}
            onClick={() => void exportAll()}
          >
            导出全部
          </Button>
        </Space>
      </Form>
      <ApiState ok={ok} error={error} traceId={traceId} />
      <Table<RawJob>
        rowKey="id"
        columns={columns}
        dataSource={rows}
        pagination={pagination}
        loading={pending}
        scroll={{ x: 1520 }}
        locale={{ emptyText: ok ? "暂无市场岗位" : "暂无数据" }}
      />
    </div>
  );
}
