"use client";

import { StatusLabel } from "@/components/StatusLabel";
import { EmptyState } from "@/components/EmptyState";
import { formatDateTime, textValue, type DataSource } from "@/lib/api";

const SOURCE_TYPE_META: Record<string, { icon: string; name: string; desc: string }> = {
  file_upload: { icon: "📤", name: "本地文件上传", desc: "通过界面上传文件，即时校验，适合少量明确文件" },
  nas: { icon: "📡", name: "NAS 同步", desc: "挂载共享目录，批量同步，事后补齐元数据" },
  crawler: { icon: "🕷", name: "Crawler 爬虫", desc: "配置爬虫规则，自动抓取 Web 页面" },
  database: { icon: "🗄", name: "数据库对接", desc: "直连数据库，按表/视图同步结构化数据" },
  webhook: { icon: "⚡", name: "API 推送", desc: "通过 Webhook/API 批量提交数据包" }
};

export function DataSourcesContent({ dataSources }: { dataSources: DataSource[] }) {
  return (
    <>
      {/* Source type cards */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">数据源类型</span>
        </div>
        <div className="card-body">
          <div className="source-type-grid">
            {Object.entries(SOURCE_TYPE_META).map(([type, meta]) => (
              <a href={`/data-sources/new?type=${type}`} key={type} className="source-type-card">
                <div className="source-type-card-icon">{meta.icon}</div>
                <div className="source-type-card-name">{meta.name}</div>
                <div className="source-type-card-desc">{meta.desc}</div>
              </a>
            ))}
          </div>
        </div>
      </div>

      {/* Registered sources */}
      {dataSources.length === 0 ? (
        <EmptyState icon="◎" title="暂无已注册数据源" description="点击上方任一类型卡片注册第一个数据源" />
      ) : (
        <div className="card">
          <div className="card-header">
            <span className="card-title">已注册数据源</span>
            <span className="text-xs text-muted">{dataSources.length} 个</span>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            {dataSources.map((source) => {
              const meta = SOURCE_TYPE_META[source.source_type];
              return (
                <a href={`/data-sources/${source.id}`} key={source.id}
                  className="table-row clickable"
                  style={{ gridTemplateColumns: "40px 1.5fr 120px 120px 120px 140px 100px", display: "grid", textDecoration: "none" }}>
                  <span style={{ fontSize: 20 }}>{meta?.icon ?? "◎"}</span>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 14 }}>{source.name}</div>
                    <span className="text-xs text-muted mono-cell">{source.code}</span>
                  </div>
                  <span className="tag">{meta?.name ?? source.source_type}</span>
                  <span className="text-sm text-muted">{textValue(source.org_scope_hint)}</span>
                  <span className="text-sm text-muted">{textValue(source.default_governance_hints)}</span>
                  <span className="text-sm text-muted">{formatDateTime(source.updated_at)}</span>
                  <StatusLabel value={source.status} />
                </a>
              );
            })}
          </div>
        </div>
      )}
    </>
  );
}
