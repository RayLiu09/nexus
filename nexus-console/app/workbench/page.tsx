import { ApiState } from "@/components/ApiState";
import { StatusLabel } from "@/components/StatusLabel";
import { formatDateTime, shortId } from "@/lib/api";
import { loadWorkbenchData } from "@/lib/console-data";

export const dynamic = "force-dynamic";

export default async function WorkbenchPage() {
  const data = await loadWorkbenchData();
  const latestBatch = data.batches.data[0];
  const latestJob = data.jobs.data[0];
  const latestAsset = data.assets.data[0];
  const latestRef = data.normalizedRefs.data[0];

  return (
    <section className="page-section">
      <div className="page-heading">
        <div>
          <p className="prototype-id">NX-01</p>
          <h1>工作台</h1>
          <p>M1 接入到资产化链路总览，覆盖批次、原始对象、作业、标准化引用和资产。</p>
        </div>
      </div>

      <ApiState ok={data.ok} error={data.error} traceId={data.traceId} />

      <div className="detail-grid">
        <div>
          <span>数据源</span>
          <strong>{data.dataSources.data.length}</strong>
        </div>
        <div>
          <span>接入批次</span>
          <strong>{data.batches.data.length}</strong>
        </div>
        <div>
          <span>原始对象</span>
          <strong>{data.rawObjects.data.length}</strong>
        </div>
        <div>
          <span>资产</span>
          <strong>{data.assets.data.length}</strong>
        </div>
        <div>
          <span>数据库</span>
          <StatusLabel value={data.runtime.data?.database ?? "failed"} />
        </div>
        <div>
          <span>审计事件</span>
          <strong>{data.audits.data.length}</strong>
        </div>
      </div>

      <div className="table-frame">
        <div className="table-row table-head">
          <span>批次号</span>
          <span>来源</span>
          <span>原始对象</span>
          <span>作业</span>
          <span>标准化引用</span>
          <span>状态</span>
        </div>
        {latestBatch ? (
          <div className="table-row">
            <span>{shortId(latestBatch.id)}</span>
            <span>{latestBatch.source_type}</span>
            <span>{shortId(data.rawObjects.data[0]?.id)}</span>
            <span>{shortId(latestJob?.id)}</span>
            <span>{shortId(latestRef?.id)}</span>
            <StatusLabel value={latestBatch.status} />
          </div>
        ) : (
          <div className="empty-state">
            <strong>暂无真实接入批次</strong>
          </div>
        )}
      </div>

      <div className="table-frame">
        <div className="table-row table-head">
          <span>最近资产</span>
          <span>版本状态</span>
          <span>最近作业</span>
          <span>更新时间</span>
        </div>
        {latestAsset ? (
          <div className="table-row">
            <span>{latestAsset.title}</span>
            <StatusLabel value={latestAsset.status} />
            <span>{latestJob?.current_stage ?? "-"}</span>
            <span>{formatDateTime(latestAsset.updated_at)}</span>
          </div>
        ) : (
          <div className="empty-state">
            <strong>暂无真实资产</strong>
          </div>
        )}
      </div>
    </section>
  );
}
