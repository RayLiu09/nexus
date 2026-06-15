"use client";

import { Card, Statistic, Table } from "antd";
import { StatusLabel } from "@/components/StatusLabel";
import { EmptyState } from "@/components/shared/EmptyState";
import { formatTime } from "@/lib/format-time";
import { shortId, type ApiCaller, type AuditLog } from "@/lib/api";

interface IamAuditContentProps {
  apiCallers: ApiCaller[];
  audits: AuditLog[];
  orgCount: number;
  userCount: number;
  apiCallerCount: number;
  auditCount: number;
}

export function IamAuditContent({
  apiCallers,
  audits,
  orgCount,
  userCount,
  apiCallerCount,
  auditCount,
}: IamAuditContentProps) {
  return (
    <>
      {/* Count cards */}
      <div className="grid gap-3 grid-cols-2 sm:grid-cols-4 mb-5">
        <Card size="small"><Statistic title="组织" value={orgCount} /></Card>
        <Card size="small"><Statistic title="用户" value={userCount} /></Card>
        <Card size="small"><Statistic title="API 调用方" value={apiCallerCount} /></Card>
        <Card size="small"><Statistic title="审计事件" value={auditCount} /></Card>
      </div>

      {/* API Callers */}
      <Card title="API 调用方" className="mb-5">
        {apiCallers.length ? (
          <Table
            rowKey="id"
            dataSource={apiCallers}
            pagination={false}
            size="small"
          >
            <Table.Column title="名称" dataIndex="name" render={(v: string) => <span style={{ fontWeight: 500 }}>{v}</span>} />
            <Table.Column title="权限范围" dataIndex="permission_scope" render={(v: string[]) => <span className="text-muted text-sm">{v.join(", ") || "-"}</span>} />
            <Table.Column title="组织范围" dataIndex="org_scope" render={(v: string[]) => <span className="text-muted text-sm">{v.map(shortId).join(", ") || "-"}</span>} />
            <Table.Column title="状态" dataIndex="status" width={100} render={(v: string) => <StatusLabel value={v} />} />
            <Table.Column
              title="更新时间"
              dataIndex="updated_at"
              width={140}
              render={(v: string) => {
                const ft = formatTime(v);
                return <time dateTime={ft.iso} title={ft.iso} className="text-muted text-sm">{ft.display}</time>;
              }}
            />
          </Table>
        ) : (
          <EmptyState title="暂无 API 调用方" size="small" />
        )}
      </Card>

      {/* Audit logs */}
      <Card title="审计日志" extra={<span className="text-muted text-xs">{audits.length} events</span>}>
        {audits.length ? (
          <Table
            rowKey="id"
            dataSource={audits}
            pagination={false}
            size="small"
          >
            <Table.Column title="事件类型" dataIndex="event_type" width={160} render={(v: string) => <span style={{ fontWeight: 500 }}>{v}</span>} />
            <Table.Column title="目标" render={(_: unknown, r: AuditLog) => <span className="text-sm">{r.target_type} / <span className="mono-cell">{shortId(r.target_id)}</span></span>} />
            <Table.Column title="Trace ID" dataIndex="trace_id" width={140} render={(v: string | null) => <span className="mono-cell">{v ?? "-"}</span>} />
            <Table.Column title="摘要" dataIndex="summary" ellipsis render={(v: Record<string, unknown>) => <span className="text-muted mono-cell text-sm">{JSON.stringify(v)}</span>} />
            <Table.Column
              title="时间"
              dataIndex="created_at"
              width={140}
              render={(v: string) => {
                const ft = formatTime(v);
                return <time dateTime={ft.iso} title={ft.iso} className="text-muted text-sm">{ft.display}</time>;
              }}
            />
          </Table>
        ) : (
          <EmptyState title="暂无审计事件" size="small" />
        )}
      </Card>
    </>
  );
}
