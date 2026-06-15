"use client";

import Link from "next/link";
import { Button, Card, Statistic, Tag, Tooltip } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { Card as SharedCard } from "@/components/shared/Card";
import { StatusLabel } from "@/components/StatusLabel";
import { EmptyState } from "@/components/shared/EmptyState";
import { formatTime } from "@/lib/format-time";
import { type DataSource } from "@/lib/api";

export interface SyncInfo {
  /** 最近一个相关 ingest_batch 的 updated_at（ISO） */
  lastSync: string | null;
  /** schedule_cron 推算的下次触发（ISO）；不支持的 cron 形态为 null */
  nextSync: string | null;
  /** 原始 cron 字符串，便于在缺失下次同步时回退展示 */
  cron: string | null;
}

const SOURCE_TYPE_META: Record<string, { icon: string; name: string; desc: string }> = {
  file_upload: { icon: "📤", name: "本地文件上传", desc: "通过界面上传文件，即时校验" },
  nas: { icon: "📡", name: "NAS 同步", desc: "挂载共享目录，批量同步" },
  crawler: { icon: "🕷", name: "Crawler 爬虫", desc: "配置规则，自动抓取 Web 页面" },
  database: { icon: "🗄", name: "数据库对接", desc: "直连数据库，按表/视图同步" },
  webhook: { icon: "⚡", name: "API 推送", desc: "通过 Webhook/API 批量提交" },
};

interface DataSourcesContentProps {
  dataSources: DataSource[];
  syncInfoByDsId: Record<string, SyncInfo>;
}

export function DataSourcesContent({ dataSources, syncInfoByDsId }: DataSourcesContentProps) {
  const activeCount = dataSources.filter((s) => s.status === "active").length;
  const typeCount = new Set(dataSources.map((s) => s.source_type)).size;

  return (
    <>
      {/* ── Metrics ── */}
      <div className="metric-grid-4 mb-5">
        <Card size="small" className="metric-secondary">
          <Statistic title="已注册数据源" value={dataSources.length} />
          <div className="text-text-muted mt-1 text-xs">{typeCount} 种类型</div>
        </Card>
        <Card size="small" className="metric-secondary">
          <Statistic
            title="活跃连接"
            value={activeCount}
            valueStyle={{ color: "var(--success-600)" }}
          />
          <div className="text-text-muted mt-1 text-xs">正常同步中</div>
        </Card>
        <Card size="small" className="metric-secondary">
          <Statistic title="数据源类型" value={Object.keys(SOURCE_TYPE_META).length} />
          <div className="text-text-muted mt-1 text-xs">支持的连接器类型</div>
        </Card>
        <Card size="small" className="metric-secondary">
          <Statistic title="默认治理策略" value="自动" />
          <div className="text-text-muted mt-1 text-xs">高置信自动采纳</div>
        </Card>
      </div>

      {/* ── Source Card Grid ── */}
      <div style={{ marginBottom: 20 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 12,
          }}
        >
          <h3 style={{ fontSize: 15, fontWeight: 600 }}>数据源连接器</h3>
          <Button type="primary" icon={<PlusOutlined />} href="/data-sources/new">
            新建数据源
          </Button>
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
            gap: 12,
          }}
        >
          {Object.entries(SOURCE_TYPE_META).map(([type, meta]) => {
            const count = dataSources.filter((s) => s.source_type === type).length;
            return (
              <SharedCard key={type} variant="interactive" weight="tertiary" className="card-hover">
                <Link
                  href={`/data-sources?type=${type}`}
                  style={{ display: "block", textDecoration: "none", color: "inherit" }}
                >
                  <div style={{ fontSize: 24, marginBottom: 8 }}>{meta.icon}</div>
                  <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>{meta.name}</div>
                  <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 8 }}>
                    {meta.desc}
                  </div>
                  {count > 0 && (
                    <Tag color="blue" style={{ fontSize: 11 }}>
                      {count} 个已注册
                    </Tag>
                  )}
                </Link>
              </SharedCard>
            );
          })}
        </div>
      </div>

      {/* ── Registered Sources List —— 窄屏横向滚动避免列挤压 ── */}
      {dataSources.length === 0 ? (
        <EmptyState title="暂无已注册数据源" hint="新建一个数据源连接器来开始接入数据" />
      ) : (
        <div
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line)",
            borderRadius: "var(--radius-xl)",
            overflow: "hidden",
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
              <div style={{ fontSize: 15, fontWeight: 600 }}>已注册数据源</div>
              <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 2 }}>
                {dataSources.length} 个数据源 · {activeCount} 个活跃
              </div>
            </div>
          </div>
          {/* 列表表头 —— overflow-x-auto 让窄屏可横向滚动 */}
          <div className="overflow-x-auto">
            <div
              className="text-text-secondary border-line-light grid items-center gap-3 border-b px-5 py-2 text-xs font-semibold"
              style={{
                gridTemplateColumns: "40px 1.3fr 100px 130px 130px 90px",
                minWidth: "680px",
              }}
            >
              <span />
              <span>名称 / 编码</span>
              <span>类型</span>
              <span>上次同步</span>
              <span>下次同步</span>
              <span>状态</span>
            </div>
            <div style={{ display: "grid", gap: 0, minWidth: "680px" }}>
              {dataSources.map((source) => {
                const meta = SOURCE_TYPE_META[source.source_type];
                const info = syncInfoByDsId[source.id];
                const isFileUpload = source.source_type === "file_upload";

                const lastSyncCell = info?.lastSync ? (
                  (() => {
                    const t = formatTime(info.lastSync);
                    return (
                      <time dateTime={t.iso} title={t.iso} className="text-text-muted text-xs">
                        {t.display}
                      </time>
                    );
                  })()
                ) : (
                  <span className="text-text-muted text-xs">从未同步</span>
                );

                let nextSyncCell: React.ReactNode;
                if (isFileUpload) {
                  nextSyncCell = (
                    <Tooltip title="文件上传类型按需触发，无定时计划">
                      <span className="text-text-muted text-xs">按需</span>
                    </Tooltip>
                  );
                } else if (info?.nextSync) {
                  const t = formatTime(info.nextSync);
                  nextSyncCell = (
                    <time
                      dateTime={t.iso}
                      title={info.cron ? `Cron: ${info.cron}` : t.iso}
                      className="text-xs"
                    >
                      {t.display}
                    </time>
                  );
                } else if (info?.cron) {
                  nextSyncCell = (
                    <Tooltip title={`Cron: ${info.cron}（无法解析展示）`}>
                      <code className="text-text-muted font-mono text-xs">{info.cron}</code>
                    </Tooltip>
                  );
                } else {
                  nextSyncCell = (
                    <Tooltip title="尚未配置定时同步">
                      <span className="text-text-muted text-xs">未配置</span>
                    </Tooltip>
                  );
                }

                return (
                  <Link
                    key={source.id}
                    href={`/data-sources/${source.id}`}
                    className="border-line-light hover:bg-bg-alt grid items-center gap-3 border-b px-5 py-3 text-inherit no-underline transition-colors"
                    style={{
                      gridTemplateColumns: "40px 1.3fr 100px 130px 130px 90px",
                      minWidth: "680px",
                    }}
                  >
                    <span style={{ fontSize: 20 }}>{meta?.icon ?? "◎"}</span>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 14 }}>{source.name}</div>
                      <code
                        style={{
                          fontSize: 11,
                          color: "var(--text-muted)",
                          fontFamily: "var(--font-mono)",
                        }}
                      >
                        {source.code}
                      </code>
                    </div>
                    <Tag>{meta?.name ?? source.source_type}</Tag>
                    {lastSyncCell}
                    {nextSyncCell}
                    <StatusLabel value={source.status} />
                  </Link>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* ── 治理前置提醒 ── */}
      {dataSources.length > 0 && (
        <div
          style={{
            marginTop: 20,
            padding: "14px 18px",
            borderRadius: "var(--radius-lg)",
            background: "var(--brand-50)",
            border: "1px solid var(--brand-200)",
            fontSize: 13,
          }}
        >
          <strong style={{ display: "block", marginBottom: 4 }}>默认治理策略</strong>
          新注册数据源默认启用「高置信自动采纳」策略。接入的数据将自动进入 AI
          治理流水线，高置信结果直接落库，低置信进入人工审核队列。
          如需调整，请在数据源详情中修改治理策略。
        </div>
      )}
    </>
  );
}
