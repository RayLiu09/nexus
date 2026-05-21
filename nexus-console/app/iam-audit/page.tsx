import { ApiState } from "@/components/ApiState";
import { PageHeader } from "@/components/PageHeader";
import { StatusLabel } from "@/components/StatusLabel";
import { StatCard } from "@/components/StatCard";
import { EmptyState } from "@/components/EmptyState";
import { formatDateTime, shortId } from "@/lib/api";
import { loadIdentityData } from "@/lib/console-data";

export const dynamic = "force-dynamic";

export default async function IamAuditPage() {
  const { orgUnits, users, apiCallers, audits } = await loadIdentityData();
  const ok = orgUnits.ok && users.ok && apiCallers.ok && audits.ok;
  const error = orgUnits.error ?? users.error ?? apiCallers.error ?? audits.error ?? null;

  return (
    <>
      <PageHeader
        eyebrow="访问与审计 — 组织、角色、API 调用方"
        title="权限与审计"
        description="本地组织用户、角色、API 调用方、组织范围和安全审计日志。"
      />

      <ApiState ok={ok} error={error} traceId={orgUnits.traceId ?? audits.traceId} />

      {/* Count cards */}
      <div className="stat-grid">
        <StatCard label="组织" value={orgUnits.data.length} variant="brand" />
        <StatCard label="用户" value={users.data.length} />
        <StatCard label="API 调用方" value={apiCallers.data.length} />
        <StatCard label="审计事件" value={audits.data.length} variant="warning" />
      </div>

      {/* API Callers */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">API 调用方</span>
        </div>
        <div className="card-body" style={{ padding: 0 }}>
          {apiCallers.data.length ? (
            apiCallers.data.map((caller) => (
              <div
                className="table-row"
                key={caller.id}
                style={{ gridTemplateColumns: "1fr 1.5fr 1fr 100px 140px" }}
              >
                <span style={{ fontWeight: 500 }}>{caller.name}</span>
                <span className="text-muted text-sm">
                  {caller.permission_scope.join(", ") || "-"}
                </span>
                <span className="text-muted text-sm">
                  {caller.org_scope.map(shortId).join(", ") || "-"}
                </span>
                <StatusLabel value={caller.status} />
                <span className="text-muted text-sm">{formatDateTime(caller.updated_at)}</span>
              </div>
            ))
          ) : (
            <EmptyState icon="⊡" title="暂无 API 调用方" />
          )}
        </div>
      </div>

      {/* Audit logs */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">审计日志</span>
          <span className="text-muted text-xs">{audits.data.length} events</span>
        </div>
        <div className="card-body" style={{ padding: 0 }}>
          {audits.data.length ? (
            audits.data.map((event) => (
              <div
                className="table-row"
                key={event.id}
                style={{ gridTemplateColumns: "160px 1fr 140px 1fr 140px" }}
              >
                <span style={{ fontWeight: 500 }}>{event.event_type}</span>
                <span className="text-sm">
                  {event.target_type} /{" "}
                  <span className="mono-cell">{shortId(event.target_id)}</span>
                </span>
                <span className="mono-cell">{event.trace_id ?? "-"}</span>
                <span className="text-muted mono-cell truncate text-sm">
                  {JSON.stringify(event.summary)}
                </span>
                <span className="text-muted text-sm">{formatDateTime(event.created_at)}</span>
              </div>
            ))
          ) : (
            <EmptyState icon="📋" title="暂无审计事件" />
          )}
        </div>
      </div>
    </>
  );
}
