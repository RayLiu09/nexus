import { ApiState } from "@/components/ApiState";
import { PageHeader } from "@/components/PageHeader";
import { StatusLabel } from "@/components/StatusLabel";
import { EmptyState } from "@/components/EmptyState";
import { formatDateTime, getApiData, shortId, type RawObject } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function RawLedgerPage() {
  const result = await getApiData<RawObject[]>("/v1/raw-objects", []);

  return (
    <>
      <PageHeader
        prototypeId="NX-04"
        title="原始数据台账"
        description="按批次和对象追溯原始留存位置、checksum、来源和接入状态。"
      />

      <ApiState ok={result.ok} error={result.error} traceId={result.traceId} />

      {result.data.length === 0 ? (
        <EmptyState icon="☰" title="暂无原始对象" description="完成数据接入后原始对象将在此处显示" />
      ) : (
        <div className="table-frame">
          <div className="table-head">
            <div className="table-row" style={{ gridTemplateColumns: "140px 140px 1fr 1fr 140px 100px" }}>
              <span>原始对象</span>
              <span>批次号</span>
              <span>对象 URI</span>
              <span>Checksum</span>
              <span>创建时间</span>
              <span>状态</span>
            </div>
          </div>
          {result.data.map((rawObject) => (
            <div className="table-row" key={rawObject.id} style={{ gridTemplateColumns: "140px 140px 1fr 1fr 140px 100px" }}>
              <span className="mono-cell">{shortId(rawObject.id)}</span>
              <span className="mono-cell">{shortId(rawObject.batch_id)}</span>
              <span className="mono-cell">{rawObject.object_uri}</span>
              <span className="mono-cell">{rawObject.checksum}</span>
              <span className="text-sm text-muted">{formatDateTime(rawObject.created_at)}</span>
              <StatusLabel value={rawObject.status} />
            </div>
          ))}
        </div>
      )}
    </>
  );
}
