import { ApiState } from "@/components/ApiState";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { DomainTag } from "@/components/DomainTag";
import { StatusLabel } from "@/components/StatusLabel";
import { EmptyState } from "@/components/EmptyState";
import { loadWorkbenchData } from "@/lib/console-data";
import { formatDateTime, shortId } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function WorkbenchPage() {
  const data = await loadWorkbenchData();
  const latestBatch = data.batches.data[0];
  const latestJob = data.jobs.data[0];
  const latestAsset = data.assets.data[0];
  const latestRef = data.normalizedRefs.data[0];

  return (
    <>
      <PageHeader
        prototypeId="NX-01"
        title="工作台"
        description="M1 接入到资产化链路总览，覆盖批次、原始对象、作业、标准化引用和资产。"
      />

      <ApiState ok={data.ok} error={data.error} traceId={data.traceId} />

      {/* Stat cards */}
      <div className="stat-grid">
        <StatCard label="数据源" value={data.dataSources.data.length} variant="brand" />
        <StatCard label="接入批次" value={data.batches.data.length} />
        <StatCard label="原始对象" value={data.rawObjects.data.length} />
        <StatCard label="资产总数" value={data.assets.data.length} variant="success" />
        <StatCard label="审计事件" value={data.audits.data.length} />
      </div>

      {/* Domain distribution + runtime status */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: "var(--space-4)" }}>
        {/* Domain distribution */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">数据域分布</span>
          </div>
          <div className="card-body">
            <div className="flex gap-3 flex-wrap">
              <DomainTag domain="D1" />
              <DomainTag domain="D2" />
              <DomainTag domain="D3" />
              <DomainTag domain="D4" />
              <DomainTag domain="D5" />
              <DomainTag domain="D6" />
            </div>
            <p className="text-sm text-muted" style={{ marginTop: "var(--space-3)" }}>
              当前展示全部数据域范围，具体分布待更多数据接入后统计。
            </p>
          </div>
        </div>

        {/* Runtime status */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">系统运行状态</span>
          </div>
          <div className="card-body">
            <div className="flex flex-col gap-3">
              <div className="flex justify-between items-center">
                <span className="text-sm text-muted">API</span>
                <StatusLabel value={data.runtime.data?.api ?? "error"} />
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-muted">数据库</span>
                <StatusLabel value={data.runtime.data?.database ?? "failed"} />
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-muted">Worker</span>
                <StatusLabel value={data.runtime.data?.workers ?? "error"} />
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-muted">队列</span>
                <StatusLabel value={data.runtime.data?.queue ?? "error"} />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Latest activity feed */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">最近活动</span>
        </div>
        <div className="card-body" style={{ padding: 0 }}>
          {latestBatch ? (
            <>
              <div className="table-row" style={{ gridTemplateColumns: "120px 1fr 120px 120px 140px" }}>
                <span className="font-bold text-sm">接入批次</span>
                <span>{shortId(latestBatch.id)}</span>
                <span>{latestBatch.source_type}</span>
                <StatusLabel value={latestBatch.status} />
                <span className="text-sm text-muted">{formatDateTime(latestBatch.created_at)}</span>
              </div>
              {latestJob && (
                <div className="table-row" style={{ gridTemplateColumns: "120px 1fr 120px 120px 140px" }}>
                  <span className="font-bold text-sm">最新作业</span>
                  <span>{shortId(latestJob.id)}</span>
                  <span>{latestJob.current_stage ?? "-"}</span>
                  <StatusLabel value={latestJob.status} />
                  <span className="text-sm text-muted">{formatDateTime(latestJob.created_at)}</span>
                </div>
              )}
              {latestAsset && (
                <div className="table-row" style={{ gridTemplateColumns: "120px 1fr 120px 120px 140px" }}>
                  <span className="font-bold text-sm">最新资产</span>
                  <span>{latestAsset.title}</span>
                  <span>{latestAsset.asset_kind}</span>
                  <StatusLabel value={latestAsset.status} />
                  <span className="text-sm text-muted">{formatDateTime(latestAsset.updated_at)}</span>
                </div>
              )}
              {latestRef && (
                <div className="table-row" style={{ gridTemplateColumns: "120px 1fr 120px 120px 140px" }}>
                  <span className="font-bold text-sm">标准化引用</span>
                  <span className="mono-cell">{shortId(latestRef.id)}</span>
                  <span>{latestRef.normalized_type}</span>
                  <StatusLabel value={latestRef.status} />
                  <span className="text-sm text-muted">{formatDateTime(latestRef.updated_at)}</span>
                </div>
              )}
            </>
          ) : (
            <EmptyState icon="📊" title="暂无活动数据" description="完成首次数据接入后将在此显示最近活动" />
          )}
        </div>
      </div>
    </>
  );
}
