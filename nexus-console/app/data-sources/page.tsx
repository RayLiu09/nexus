import { ApiState } from "@/components/ApiState";
import { StatusLabel } from "@/components/StatusLabel";
import { formatDateTime, textValue } from "@/lib/api";
import { getApiData, type DataSource } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function DataSourcesPage() {
  const result = await getApiData<DataSource[]>("/v1/data-sources", []);

  return (
    <section className="page-section">
      <div className="page-heading">
        <div>
          <p className="prototype-id">NX-02</p>
          <h1>数据源管理</h1>
          <p>数据源注册、上传入口、NAS 同步和爬虫推送配置。</p>
        </div>
      </div>

      <ApiState ok={result.ok} error={result.error} traceId={result.traceId} />

      <div className="table-frame">
        <div className="table-row table-head">
          <span>名称</span>
          <span>编码</span>
          <span>类型</span>
          <span>业务域提示</span>
          <span>组织提示</span>
          <span>最近同步</span>
          <span>状态</span>
        </div>
        {result.data.length ? (
          result.data.map((source) => (
            <div className="table-row" key={source.id}>
              <span>{source.name}</span>
              <span>{source.code}</span>
              <span>{source.source_type}</span>
              <span>{textValue(source.default_governance_hints)}</span>
              <span>{textValue(source.org_scope_hint)}</span>
              <span>{formatDateTime(source.updated_at)}</span>
              <StatusLabel value={source.status} />
            </div>
          ))
        ) : (
          <div className="empty-state">
            <strong>暂无真实数据源</strong>
          </div>
        )}
      </div>
    </section>
  );
}
