"use client";

import { useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Card, Select, Table } from "antd";
import type { ColumnsType, TablePaginationConfig } from "antd/es/table";
import { EmptyState } from "@/components/shared/EmptyState";
import { formatTime } from "@/lib/format-time";
import type { AuditLog } from "@/lib/api";
import { DEFAULT_PAGE_SIZE } from "@/lib/pagination";

const TARGET_TYPE_LABELS: Record<string, string> = {
  asset: "资产",
  asset_version: "资产版本",
  normalized_asset_ref: "标准化资产",
  raw_object: "原始对象",
  ingest_batch: "接入批次",
  job: "作业",
  parse_artifact: "解析产物",
  governance_result: "治理结果",
  ai_governance_run: "AI 治理任务",
  knowledge_chunk: "知识切片",
  data_source: "数据源",
  crawler_plan: "Crawler 计划",
  crawler_run: "Crawler 运行",
  data_sync_config: "API 同步计划",
  data_sync_run: "API 同步运行",
  user_account: "用户",
  api_caller: "API 调用方",
  org_unit: "组织",
  ai_prompt_profile: "Prompt 配置",
  governance_prompt_template: "治理 Prompt 模板",
};

const SUMMARY_LABELS: Record<string, string> = {
  reason: "原因",
  status: "状态",
  from_status: "原状态",
  to_status: "新状态",
  changed_fields: "变更字段",
  asset_title: "资产名称",
  filename: "文件名",
  name: "名称",
  mode: "模式",
  execution_mode: "执行方式",
  schedule_cron: "调度规则",
  failed_count: "失败数",
  submitted_count: "提交数",
  accepted_count: "接收数",
  duplicate_count: "重复数",
};

function summarize(summary: Record<string, unknown>): string {
  return (
    Object.entries(summary)
      .map(
        ([key, value]) =>
          `${SUMMARY_LABELS[key] ?? key}：${
            typeof value === "string" ? value : JSON.stringify(value)
          }`,
      )
      .join("；") || "—"
  );
}

interface IamAuditContentProps {
  audits: AuditLog[];
  eventTypes: string[];
  eventType?: string;
  totalCount: number;
  currentPage: number;
  pageSize: number;
}

export function IamAuditContent({
  audits,
  eventTypes,
  eventType,
  totalCount,
  currentPage,
  pageSize,
}: IamAuditContentProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [pending, startTransition] = useTransition();

  function navigate(nextEvent: string | undefined, page: number, size: number) {
    const params = new URLSearchParams();
    if (nextEvent) params.set("event_type", nextEvent);
    if (page > 1) params.set("page", String(page));
    if (size !== DEFAULT_PAGE_SIZE) params.set("pageSize", String(size));
    const query = params.toString();
    startTransition(() => router.replace(query ? `${pathname}?${query}` : pathname));
  }

  const columns: ColumnsType<AuditLog> = [
    {
      title: "事件类型",
      dataIndex: "event_type",
      width: 220,
    },
    {
      title: "操作目标类型",
      dataIndex: "target_type",
      width: 150,
      render: (value: string) => TARGET_TYPE_LABELS[value] ?? value,
    },
    {
      title: "目标名称",
      width: 240,
      render: (_, row) => <span title={row.target_id}>{row.target_name || row.target_id}</span>,
    },
    {
      title: "操作者",
      width: 150,
      render: (_, row) => (
        <span title={row.actor_id ?? undefined}>
          {row.actor_name || row.actor_id || "未记录"}
        </span>
      ),
    },
    {
      title: "摘要",
      width: 360,
      render: (_, row) => {
        const text = summarize(row.summary);
        return (
          <span title={text} className="line-clamp-2 break-all">
            {text}
          </span>
        );
      },
    },
    {
      title: "操作时间",
      dataIndex: "created_at",
      width: 180,
      render: (value: string) => {
        const time = formatTime(value);
        return (
          <time dateTime={time.iso} title={time.iso}>
            {time.display}
          </time>
        );
      },
    },
  ];

  function onTableChange(pagination: TablePaginationConfig) {
    const size = pagination.pageSize ?? pageSize;
    navigate(eventType, size === pageSize ? (pagination.current ?? 1) : 1, size);
  }

  return (
    <Card>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <span className="text-muted text-sm">共 {totalCount} 条审计日志</span>
        <div className="flex items-center gap-2">
          <label htmlFor="audit-event-type">事件类型</label>
          <Select
            id="audit-event-type"
            aria-label="事件类型"
            allowClear
            showSearch
            placeholder="全部事件类型"
            value={eventType}
            options={eventTypes.map((value) => ({ value, label: value }))}
            onChange={(value) => navigate(value, 1, pageSize)}
            style={{ width: 300 }}
          />
        </div>
      </div>
      <Table<AuditLog>
        rowKey="id"
        dataSource={audits}
        columns={columns}
        loading={pending}
        size="small"
        scroll={{ x: 1300 }}
        pagination={{
          current: currentPage,
          pageSize,
          total: totalCount,
          showSizeChanger: true,
          showTotal: (total, range) => `${range[0]}-${range[1]} / ${total}`,
        }}
        onChange={onTableChange}
        locale={{ emptyText: <EmptyState title="暂无审计日志" size="small" /> }}
      />
    </Card>
  );
}
