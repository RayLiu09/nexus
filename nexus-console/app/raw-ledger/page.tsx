import { ApiState } from "@/components/ApiState";
import { StatusLabel } from "@/components/StatusLabel";
import { formatDateTime, getApiData, shortId, type RawObject } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function RawLedgerPage() {
  const result = await getApiData<RawObject[]>("/v1/raw-objects", []);

  return (
    <section className="page-section">
      <div className="page-heading">
        <div>
          <p className="prototype-id">NX-04</p>
          <h1>原始数据台账</h1>
          <p>按批次和对象追溯原始留存位置、checksum、来源和接入状态。</p>
        </div>
      </div>

      <ApiState ok={result.ok} error={result.error} traceId={result.traceId} />

      <div className="table-frame">
        <div className="table-row table-head">
          <span>原始对象</span>
          <span>批次号</span>
          <span>对象 URI</span>
          <span>Checksum</span>
          <span>创建时间</span>
          <span>状态</span>
        </div>
        {result.data.length ? (
          result.data.map((rawObject) => (
            <div className="table-row" key={rawObject.id}>
              <span>{shortId(rawObject.id)}</span>
              <span>{shortId(rawObject.batch_id)}</span>
              <span className="mono-cell">{rawObject.object_uri}</span>
              <span className="mono-cell">{rawObject.checksum}</span>
              <span>{formatDateTime(rawObject.created_at)}</span>
              <StatusLabel value={rawObject.status} />
            </div>
          ))
        ) : (
          <div className="empty-state">
            <strong>暂无真实原始对象</strong>
          </div>
        )}
      </div>
    </section>
  );
}
