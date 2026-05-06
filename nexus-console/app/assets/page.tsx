import Link from "next/link";
import { ApiState } from "@/components/ApiState";
import { StatusLabel } from "@/components/StatusLabel";
import { formatDateTime, getApiData, shortId, type DocumentAsset } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function AssetsPage() {
  const result = await getApiData<DocumentAsset[]>("/v1/assets", []);

  return (
    <section className="page-section">
      <div className="page-heading">
        <div>
          <p className="prototype-id">NX-06</p>
          <h1>资产目录</h1>
          <p>展示由接入链路生成的资产、派生当前版本和标准化引用。</p>
        </div>
      </div>

      <ApiState ok={result.ok} error={result.error} traceId={result.traceId} />

      <div className="table-frame">
        <div className="table-row table-head">
          <span>标题</span>
          <span>资产ID</span>
          <span>类型</span>
          <span>数据源</span>
          <span>更新时间</span>
          <span>状态</span>
          <span>操作</span>
        </div>
        {result.data.length ? (
          result.data.map((asset) => (
            <div className="table-row" key={asset.id}>
              <span>{asset.title}</span>
              <span>{shortId(asset.id)}</span>
              <span>{asset.asset_kind}</span>
              <span>{shortId(asset.data_source_id)}</span>
              <span>{formatDateTime(asset.updated_at)}</span>
              <StatusLabel value={asset.status} />
              <Link className="text-link" href={`/assets/${asset.id}`}>
                查看详情
              </Link>
            </div>
          ))
        ) : (
          <div className="empty-state">
            <strong>暂无真实资产</strong>
          </div>
        )}
      </div>
    </section>
  );
}
