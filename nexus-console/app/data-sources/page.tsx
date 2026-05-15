import Link from "next/link";
import { ApiState } from "@/components/ApiState";
import { PageHeader } from "@/components/PageHeader";
import { StatusLabel } from "@/components/StatusLabel";
import { EmptyState } from "@/components/EmptyState";
import { StatCard } from "@/components/StatCard";
import { formatDateTime, textValue } from "@/lib/api";
import { getApiData, type DataSource } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function DataSourcesPage() {
  const result = await getApiData<DataSource[]>("/v1/data-sources", []);

  return (
    <>
      <PageHeader
        prototypeId="NX-02"
        title="数据源管理"
        description="数据源注册、上传入口、NAS 同步和爬虫推送配置。管理数据源的连接状态和治理提示。"
        actions={
          <Link href="/ingest" className="btn btn-primary">
            + 新建数据源
          </Link>
        }
      />

      <ApiState ok={result.ok} error={result.error} traceId={result.traceId} />

      {/* Source type cards */}
      <div className="stat-grid">
        <StatCard label="文件上传源" value={result.data.filter((s) => s.source_type === "file_upload").length} variant="brand" />
        <StatCard label="NAS 同步源" value={result.data.filter((s) => s.source_type === "nas_sync").length} />
        <StatCard label="Web 爬虫源" value={result.data.filter((s) => s.source_type === "web_crawl").length} />
        <StatCard label="API 推送源" value={result.data.filter((s) => s.source_type === "api_push").length} />
      </div>

      {/* Data source table */}
      {result.data.length === 0 ? (
        <EmptyState icon="◎" title="暂无数据源" description="注册第一个数据源以开始数据接入" />
      ) : (
        <div className="table-frame">
          <div className="table-head">
            <div className="table-row" style={{ gridTemplateColumns: "1.5fr 100px 100px 120px 120px 140px 100px" }}>
              <span>名称</span>
              <span>编码</span>
              <span>类型</span>
              <span>业务域提示</span>
              <span>组织提示</span>
              <span>最近同步</span>
              <span>状态</span>
            </div>
          </div>
          {result.data.map((source) => (
            <div className="table-row clickable" key={source.id} style={{ gridTemplateColumns: "1.5fr 100px 100px 120px 120px 140px 100px" }}>
              <span style={{ fontWeight: 500 }}>{source.name}</span>
              <span className="mono-cell">{source.code}</span>
              <span className="tag">{source.source_type}</span>
              <span className="text-sm text-muted">{textValue(source.default_governance_hints)}</span>
              <span className="text-sm text-muted">{textValue(source.org_scope_hint)}</span>
              <span className="text-sm text-muted">{formatDateTime(source.updated_at)}</span>
              <StatusLabel value={source.status} />
            </div>
          ))}
        </div>
      )}
    </>
  );
}
