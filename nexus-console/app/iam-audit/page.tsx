import { ApiState } from "@/components/ApiState";
import { StatusLabel } from "@/components/StatusLabel";
import { formatDateTime, shortId } from "@/lib/api";
import { loadIdentityData } from "@/lib/console-data";

export const dynamic = "force-dynamic";

export default async function IamAuditPage() {
  const { orgUnits, users, apiCallers, audits } = await loadIdentityData();
  const ok = orgUnits.ok && users.ok && apiCallers.ok && audits.ok;
  const error =
    orgUnits.error ?? users.error ?? apiCallers.error ?? audits.error ?? null;

  return (
    <section className="page-section">
      <div className="page-heading">
        <div>
          <p className="prototype-id">NX-10</p>
          <h1>权限与审计</h1>
          <p>本地组织用户、角色、API 调用方、组织范围和 Week1/2 审计日志。</p>
        </div>
      </div>

      <ApiState ok={ok} error={error} traceId={orgUnits.traceId ?? audits.traceId} />

      <div className="detail-grid">
        <div>
          <span>组织</span>
          <strong>{orgUnits.data.length}</strong>
        </div>
        <div>
          <span>用户</span>
          <strong>{users.data.length}</strong>
        </div>
        <div>
          <span>API 调用方</span>
          <strong>{apiCallers.data.length}</strong>
        </div>
        <div>
          <span>审计事件</span>
          <strong>{audits.data.length}</strong>
        </div>
      </div>

      <div className="table-frame">
        <div className="table-row table-head">
          <span>调用方</span>
          <span>权限范围</span>
          <span>组织范围</span>
          <span>状态</span>
          <span>更新时间</span>
        </div>
        {apiCallers.data.length ? (
          apiCallers.data.map((caller) => (
            <div className="table-row" key={caller.id}>
              <span>{caller.name}</span>
              <span>{caller.permission_scope.join(", ") || "-"}</span>
              <span>{caller.org_scope.map(shortId).join(", ") || "-"}</span>
              <StatusLabel value={caller.status} />
              <span>{formatDateTime(caller.updated_at)}</span>
            </div>
          ))
        ) : (
          <div className="empty-state">
            <strong>暂无 API 调用方</strong>
          </div>
        )}
      </div>

      <div className="table-frame">
        <div className="table-row table-head">
          <span>事件</span>
          <span>对象</span>
          <span>Trace</span>
          <span>摘要</span>
          <span>时间</span>
        </div>
        {audits.data.length ? (
          audits.data.map((event) => (
            <div className="table-row" key={event.id}>
              <span>{event.event_type}</span>
              <span>
                {event.target_type} / {shortId(event.target_id)}
              </span>
              <span className="mono-cell">{event.trace_id ?? "-"}</span>
              <span className="mono-cell">{JSON.stringify(event.summary)}</span>
              <span>{formatDateTime(event.created_at)}</span>
            </div>
          ))
        ) : (
          <div className="empty-state">
            <strong>暂无审计事件</strong>
          </div>
        )}
      </div>
    </section>
  );
}
