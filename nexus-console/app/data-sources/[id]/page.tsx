import Link from "next/link";
import { Empty } from "antd";

import { PageHeader } from "@/components/PageHeader";
import { ApiState } from "@/components/ApiState";
import { StatusLabel } from "@/components/StatusLabel";
import { Card } from "@/components/shared/Card";
import { formatTime } from "@/lib/format-time";
import { getApiData, shortId, type DataSource, type IngestBatch, type RawObject } from "@/lib/api";

import { ConnectorConfig } from "./_components/ConnectorConfig";
import { DeleteDataSourceButton } from "./_components/DeleteDataSourceButton";
import { DetailTabs } from "./_components/DetailTabs";
import { SyncControlPanel } from "./_components/SyncControlPanel";
import { SyncHistoryPanel } from "./_components/SyncHistoryPanel";

export const dynamic = "force-dynamic";

const SOURCE_TYPE_META: Record<string, { icon: string; name: string }> = {
  file_upload: { icon: "📤", name: "本地文件上传" },
  nas: { icon: "📡", name: "NAS 同步" },
  crawler: { icon: "🕷", name: "Crawler 爬虫" },
  database: { icon: "🗄", name: "数据库对接" },
  webhook: { icon: "⚡", name: "API 推送" },
};

function byUpdatedAtDesc(a: { updated_at: string }, b: { updated_at: string }) {
  return b.updated_at.localeCompare(a.updated_at);
}

export default async function DataSourceDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  const [dsResult, batchesResult, rawResult] = await Promise.all([
    getApiData<DataSource | null>(`/internal/v1/data-sources/${id}`, null),
    getApiData<IngestBatch[]>("/internal/v1/ingest/batches", []),
    getApiData<RawObject[]>("/internal/v1/raw-objects", []),
  ]);

  const ds = dsResult.data;
  const relatedBatches = batchesResult.data
    .filter((b) => b.data_source_id === id)
    .sort(byUpdatedAtDesc);
  const relatedRaw = rawResult.data.filter((r) => r.data_source_id === id);
  const meta = ds ? SOURCE_TYPE_META[ds.source_type] : null;

  return (
    <>
      <PageHeader
        eyebrow="数据源 — 详情"
        title={ds ? `${meta?.icon ?? "◎"} ${ds.name}` : `数据源 ${shortId(id)}`}
        description={ds?.description ?? "查看数据源配置、同步控制和接入历史。"}
        actions={
          <Link href="/data-sources" className="text-brand text-sm">
            ← 返回数据源列表
          </Link>
        }
      />

      <ApiState ok={dsResult.ok} error={dsResult.error} traceId={dsResult.traceId} />

      {!ds ? (
        <Empty description="数据源不存在" />
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

          <DetailTabs
            config={
              <div className="grid gap-4">
                {/* ── 基础信息 ── */}
                <div className="bg-surface border-line rounded-xl border p-5">
                  <div className="mb-3 text-base font-semibold">基础信息</div>
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
                      <strong className="text-sm">
                        {ds.org_scope_hint?.length > 0 ? ds.org_scope_hint.join(", ") : "-"}
                      </strong>
                    </div>
                    <div>
                      <span>创建时间</span>
                      <strong className="text-sm">{formatTime(ds.created_at).display}</strong>
                    </div>
                    <div>
                      <span>最近更新</span>
                      <strong className="text-sm">{formatTime(ds.updated_at).display}</strong>
                    </div>
                  </div>
                </div>

                {/* ── 连接器配置 ── */}
                <ConnectorConfig dataSource={ds} />

                {/* ── 默认治理预设 ── */}
                {Object.keys(ds.default_governance_hints || {}).length > 0 && (
                  <div className="bg-surface border-line rounded-xl border p-5">
                    <div className="text-base font-semibold">默认治理预设</div>
                    <div className="text-text-secondary mt-1 mb-3 text-xs">
                      此数据源的默认治理建议（分类、分级、标签提示），由 AI 治理流水线参考使用
                    </div>
                    <pre className="bg-surface-alt border-line-light max-h-[200px] overflow-auto rounded-lg border p-3 font-mono text-xs">
                      {JSON.stringify(ds.default_governance_hints, null, 2)}
                    </pre>
                  </div>
                )}

                {/* ── 危险操作 ── */}
                <div className="bg-surface rounded-xl border border-red-200 p-5">
                  <div className="text-danger text-base font-semibold">危险操作</div>
                  <div className="text-text-secondary mt-1 mb-3 text-xs">
                    删除数据源是不可逆操作。请确认已无关联的活跃作业后再执行。
                  </div>
                  <DeleteDataSourceButton dataSourceId={ds.id} dataSourceName={ds.name} />
                </div>
              </div>
            }
            sync={<SyncControlPanel dataSource={ds} relatedBatches={relatedBatches} />}
            history={<SyncHistoryPanel batches={relatedBatches} />}
          />
        </>
      )}
    </>
  );
}
