"use client";

import { useMemo, useState } from "react";
import { Card, Statistic, Table } from "antd";
import type { TablePaginationConfig } from "antd/es/table";
import { StatusLabel } from "@/components/StatusLabel";
import { EmptyState } from "@/components/shared/EmptyState";
import { formatTime } from "@/lib/format-time";
import { shortId, type ApiCaller, type AuditLog } from "@/lib/api";
import { DEFAULT_PAGE_SIZE } from "@/lib/pagination";

const IGNORED_EVENTS = new Set(["TokenRefreshed", "TokenRefreshFailed"]);
const MAX_AGE_DAYS = 30;

function isWithinDays(dateStr: string, days: number): boolean {
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
  return new Date(dateStr).getTime() >= cutoff;
}

interface IamAuditContentProps {
  apiCallers: ApiCaller[];
  audits: AuditLog[];
  orgCount: number;
  userCount: number;
  apiCallerCount: number;
  auditTotal: number;
}

export function IamAuditContent({
  apiCallers,
  audits,
  orgCount,
  userCount,
  apiCallerCount,
  auditTotal,
}: IamAuditContentProps) {
  const [pagination, setPagination] = useState<TablePaginationConfig>({
    current: 1,
    pageSize: DEFAULT_PAGE_SIZE,
  });

  const filtered = useMemo(
    () =>
      audits.filter(
        (a) => !IGNORED_EVENTS.has(a.event_type) && isWithinDays(a.created_at, MAX_AGE_DAYS),
      ),
    [audits],
  );

  return (
    <>
      {/* Count cards */}
      <div className="grid gap-3 grid-cols-2 sm:grid-cols-4 mb-5">
        <Card size="small">
          <Statistic title="组织" value={orgCount} />
        </Card>
        <Card size="small">
          <Statistic title="用户" value={userCount} />
        </Card>
        <Card size="small">
          <Statistic title="API 调用方" value={apiCallerCount} />
        </Card>
        <Card size="small">
          <Statistic title={`近${MAX_AGE_DAYS}天审计事件`} value={filtered.length} />
        </Card>
      </div>

      {/* API Callers */}
      <Card title="API 调用方" className="mb-5">
        {apiCallers.length ? (
          <Table rowKey="id" dataSource={apiCallers} pagination={false} size="small">
            <Table.Column
              title="名称"
              dataIndex="name"
              render={(v: string) => <span style={{ fontWeight: 500 }}>{v}</span>}
            />
            <Table.Column
              title="权限范围"
              dataIndex="permission_scope"
              render={(v: string[]) => (
                <span className="text-muted text-sm">{v.join(", ") || "-"}</span>
              )}
            />
            <Table.Column
              title="组织范围"
              dataIndex="org_scope"
              render={(v: string[]) => (
                <span className="text-muted text-sm">{v.map(shortId).join(", ") || "-"}</span>
              )}
            />
            <Table.Column
              title="状态"
              dataIndex="status"
              width={100}
              render={(v: string) => <StatusLabel value={v} />}
            />
            <Table.Column
              title="更新时间"
              dataIndex="updated_at"
              width={140}
              render={(v: string) => {
                const ft = formatTime(v);
                return (
                  <time dateTime={ft.iso} title={ft.iso} className="text-muted text-sm">
                    {ft.display}
                  </time>
                );
              }}
            />
          </Table>
        ) : (
          <EmptyState title="暂无 API 调用方" size="small" />
        )}
      </Card>

      {/* Audit logs */}
      <Card
        title="审计日志"
        extra={
          <span className="text-muted text-xs">
            {filtered.length} / {auditTotal} events
          </span>
        }
      >
        {filtered.length ? (
          <Table
            rowKey="id"
            dataSource={filtered}
            pagination={{
              ...pagination,
              total: filtered.length,
              showSizeChanger: true,
              showTotal: (total, range) => `${range[0]}-${range[1]} / ${total}`,
              onChange: (page, pageSize) => setPagination({ current: page, pageSize }),
            }}
            size="small"
          >
            <Table.Column
              title="事件类型"
              dataIndex="event_type"
              width={180}
              render={(v: string) => <span style={{ fontWeight: 500 }}>{v}</span>}
            />
            <Table.Column
              title="目标"
              render={(_: unknown, r: AuditLog) => (
                <span className="text-sm">
                  {r.target_type} / <span className="mono-cell">{shortId(r.target_id)}</span>
                </span>
              )}
            />
            <Table.Column
              title="操作者"
              dataIndex="actor_id"
              width={120}
              render={(v: string | null) => (
                <span className="mono-cell">{v ? shortId(v) : "-"}</span>
              )}
            />
            <Table.Column
              title="Trace ID"
              dataIndex="trace_id"
              width={140}
              render={(v: string | null) => <span className="mono-cell">{v ?? "-"}</span>}
            />
            <Table.Column
              title="摘要"
              dataIndex="summary"
              ellipsis
              render={(v: Record<string, unknown>) => (
                <span className="text-muted mono-cell text-sm">{JSON.stringify(v)}</span>
              )}
            />
            <Table.Column
              title="时间"
              dataIndex="created_at"
              width={140}
              defaultSortOrder="descend"
              sorter={(a: AuditLog, b: AuditLog) =>
                new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
              }
              render={(v: string) => {
                const ft = formatTime(v);
                return (
                  <time dateTime={ft.iso} title={ft.iso} className="text-muted text-sm">
                    {ft.display}
                  </time>
                );
              }}
            />
          </Table>
        ) : (
          <EmptyState title="暂无审计事件" size="small" hint={`近${MAX_AGE_DAYS}天内无审计日志`} />
        )}
      </Card>
    </>
  );
}
