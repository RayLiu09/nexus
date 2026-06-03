import Link from "next/link";
import { PageHeader } from "@/components/PageHeader";
import { ApiState } from "@/components/ApiState";
import { StatusLabel } from "@/components/StatusLabel";
import { Card } from "@/components/shared/Card";
import { Empty } from "@/components/shared/Empty";
import { formatTime } from "@/lib/format-time";
import { getApiData, shortId, type DataSource, type IngestBatch, type RawObject } from "@/lib/api";
import { ConnectorConfig } from "./_components/ConnectorConfig";
import { DeleteDataSourceButton } from "./_components/DeleteDataSourceButton";

export const dynamic = "force-dynamic";

const SOURCE_TYPE_META: Record<string, { icon: string; name: string }> = {
  file_upload: { icon: "📤", name: "本地文件上传" },
  nas: { icon: "📡", name: "NAS 同步" },
  crawler: { icon: "🕷", name: "Crawler 爬虫" },
  database: { icon: "🗄", name: "数据库对接" },
  webhook: { icon: "⚡", name: "API 推送" },
};

export default async function DataSourceDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  const [dsResult, batchesResult, rawResult] = await Promise.all([
    getApiData<DataSource | null>(`/v1/data-sources/${id}`, null),
    getApiData<IngestBatch[]>("/v1/ingest/batches", []),
    getApiData<RawObject[]>("/v1/raw-objects", []),
  ]);

  const ds = dsResult.data;
  const relatedBatches = batchesResult.data.filter((b) => b.data_source_id === id);
  const relatedRaw = rawResult.data.filter((r) => r.data_source_id === id);
  const meta = ds ? SOURCE_TYPE_META[ds.source_type] : null;

  return (
    <>
      <PageHeader
        eyebrow="数据源管理 — 详情"
        title={ds ? `${meta?.icon ?? "◎"} ${ds.name}` : `数据源 ${shortId(id)}`}
        description={ds?.description ?? "查看数据源配置、关联批次和原始对象。"}
        actions={
          <Link href="/data-sources" style={{ fontSize: 13, color: "var(--brand)" }}>
            ← 返回数据源列表
          </Link>
        }
      />

      <ApiState ok={dsResult.ok} error={dsResult.error} traceId={dsResult.traceId} />

      {!ds ? (
        <Empty title="数据源不存在" description="该数据源可能已被删除或 ID 错误" />
      ) : (
        <>
          {/* ── Metrics ── */}
          <div className="metric-grid-4">
            <Card variant="metric" weight="secondary">
              <div className="card-label">连接器类型</div>
              <div className="card-value" style={{ fontSize: 18 }}>
                {meta?.name ?? ds.source_type}
              </div>
              <div className="card-sub">{ds.source_type}</div>
            </Card>
            <Card
              variant="metric"
              weight="secondary"
              tone={ds.status === "active" ? "success" : "default"}
            >
              <div className="card-label">状态</div>
              <div className="card-value" style={{ fontSize: 18 }}>
                <StatusLabel value={ds.status} />
              </div>
              <div className="card-sub">运营状态</div>
            </Card>
            <Card variant="metric" weight="secondary">
              <div className="card-label">关联批次</div>
              <div className="card-value">{relatedBatches.length}</div>
              <div className="card-sub">累计接入次数</div>
            </Card>
            <Card variant="metric" weight="secondary">
              <div className="card-label">原始对象</div>
              <div className="card-value">{relatedRaw.length}</div>
              <div className="card-sub">已留存对象数</div>
            </Card>
          </div>

          {/* ── Configuration ── */}
          <div
            style={{
              background: "var(--surface)",
              border: "1px solid var(--line)",
              borderRadius: "var(--radius-xl)",
              padding: 20,
              marginBottom: 20,
            }}
          >
            <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>基础信息</div>
            <div className="detail-grid">
              <div>
                <span>数据源编码</span>
                <strong className="mono-cell">{ds.code}</strong>
              </div>
              <div>
                <span>数据源 ID</span>
                <strong className="mono-cell">{ds.id}</strong>
              </div>
              <div>
                <span>负责人</span>
                <strong className="mono-cell">{shortId(ds.owner_user_id) || "-"}</strong>
              </div>
              <div>
                <span>组织范围</span>
                <strong style={{ fontSize: 13 }}>
                  {ds.org_scope_hint?.length > 0 ? ds.org_scope_hint.join(", ") : "-"}
                </strong>
              </div>
              <div>
                <span>创建时间</span>
                <strong style={{ fontSize: 13 }}>{formatTime(ds.created_at).display}</strong>
              </div>
              <div>
                <span>最近更新</span>
                <strong style={{ fontSize: 13 }}>{formatTime(ds.updated_at).display}</strong>
              </div>
            </div>
          </div>

          {/* ── Connector Config ── */}
          <ConnectorConfig dataSource={ds} />

          {/* ── Governance Hints ── */}
          {Object.keys(ds.default_governance_hints || {}).length > 0 && (
            <div
              style={{
                background: "var(--surface)",
                border: "1px solid var(--line)",
                borderRadius: "var(--radius-xl)",
                padding: 20,
                marginBottom: 20,
              }}
            >
              <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>默认治理预设</div>
              <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 12 }}>
                此数据源的默认治理建议（分类、分级、标签提示），由 AI 治理流水线参考使用
              </div>
              <pre
                style={{
                  margin: 0,
                  padding: 12,
                  background: "var(--surface-alt)",
                  border: "1px solid var(--line-light)",
                  borderRadius: "var(--radius-lg)",
                  fontSize: 12,
                  fontFamily: "var(--font-mono)",
                  overflow: "auto",
                  maxHeight: 200,
                }}
              >
                {JSON.stringify(ds.default_governance_hints, null, 2)}
              </pre>
            </div>
          )}

          {/* ── Danger Zone ── */}
          <div
            style={{
              background: "var(--surface)",
              border: "1px solid var(--danger-200, #fecaca)",
              borderRadius: "var(--radius-xl)",
              padding: 20,
              marginBottom: 20,
            }}
          >
            <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4, color: "var(--danger-600, #dc2626)" }}>
              危险操作
            </div>
            <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 12 }}>
              删除数据源是不可逆操作。请确认已无关联的活跃作业后再执行。
            </div>
            <DeleteDataSourceButton dataSourceId={ds.id} dataSourceName={ds.name} />
          </div>

          {/* ── Related Batches ── */}
          <div
            style={{
              background: "var(--surface)",
              border: "1px solid var(--line)",
              borderRadius: "var(--radius-xl)",
              overflow: "hidden",
              marginBottom: 20,
            }}
          >
            <div
              style={{
                padding: "16px 20px",
                borderBottom: "1px solid var(--line-light)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <div>
                <div style={{ fontSize: 15, fontWeight: 600 }}>关联批次</div>
                <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 2 }}>
                  {relatedBatches.length} 个批次通过此数据源接入
                </div>
              </div>
              <Link href="/ingest" style={{ fontSize: 13, color: "var(--brand)" }}>
                新建批次 →
              </Link>
            </div>
            {relatedBatches.length === 0 ? (
              <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>
                暂无批次。前往{" "}
                <Link href="/ingest" style={{ color: "var(--brand)" }}>
                  数据接入
                </Link>{" "}
                提交首个批次。
              </div>
            ) : (
              <>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "140px 1fr 100px 130px 90px",
                    gap: 12,
                    padding: "8px 20px",
                    borderBottom: "1px solid var(--line-light)",
                    fontSize: 12,
                    fontWeight: 600,
                    color: "var(--text-secondary)",
                  }}
                >
                  <span>批次 ID</span>
                  <span>幂等键</span>
                  <span>类型</span>
                  <span>更新时间</span>
                  <span>状态</span>
                </div>
                {relatedBatches.slice(0, 10).map((b) => {
                  const t = formatTime(b.updated_at);
                  return (
                    <div
                      key={b.id}
                      style={{
                        display: "grid",
                        gridTemplateColumns: "140px 1fr 100px 130px 90px",
                        gap: 12,
                        padding: "10px 20px",
                        borderBottom: "1px solid var(--line-light)",
                        fontSize: 13,
                        alignItems: "center",
                      }}
                    >
                      <code style={{ fontSize: 11, fontFamily: "var(--font-mono)" }}>
                        {shortId(b.id)}
                      </code>
                      <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                        {b.idempotency_key}
                      </span>
                      <span style={{ fontSize: 12 }}>{b.source_type}</span>
                      <time
                        dateTime={t.iso}
                        title={t.iso}
                        style={{ fontSize: 12, color: "var(--text-muted)" }}
                      >
                        {t.display}
                      </time>
                      <StatusLabel value={b.status} />
                    </div>
                  );
                })}
              </>
            )}
          </div>
        </>
      )}
    </>
  );
}
