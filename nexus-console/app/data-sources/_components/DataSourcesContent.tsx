"use client";

import Link from "next/link";
import { Button, Tag } from "antd";
import { PlusOutlined, SyncOutlined } from "@ant-design/icons";
import { Card } from "@/components/shared/Card";
import { StatusDot } from "@/components/shared/StatusDot";
import { formatTime } from "@/lib/format-time";
import { type DataSource } from "@/lib/api";

const SOURCE_TYPE_META: Record<string, { icon: string; name: string; desc: string }> = {
  file_upload: { icon: "📤", name: "本地文件上传", desc: "通过界面上传文件，即时校验" },
  nas: { icon: "📡", name: "NAS 同步", desc: "挂载共享目录，批量同步" },
  crawler: { icon: "🕷", name: "Crawler 爬虫", desc: "配置规则，自动抓取 Web 页面" },
  database: { icon: "🗄", name: "数据库对接", desc: "直连数据库，按表/视图同步" },
  webhook: { icon: "⚡", name: "API 推送", desc: "通过 Webhook/API 批量提交" },
};

const STATUS_TONE: Record<string, "success" | "warning" | "danger" | "neutral" | "info"> = {
  active: "success",
  inactive: "neutral",
  error: "danger",
  syncing: "info",
};

export function DataSourcesContent({ dataSources }: { dataSources: DataSource[] }) {
  const activeCount = dataSources.filter((s) => s.status === "active").length;
  const typeCount = new Set(dataSources.map((s) => s.source_type)).size;

  return (
    <>
      {/* ── Metrics ── */}
      <div className="metric-grid-4">
        <Card variant="metric" weight="secondary">
          <div className="card-label">已注册数据源</div>
          <div className="card-value">{dataSources.length}</div>
          <div className="card-sub">{typeCount} 种类型</div>
        </Card>
        <Card variant="metric" weight="secondary" tone="success">
          <div className="card-label">活跃连接</div>
          <div className="card-value">{activeCount}</div>
          <div className="card-sub">正常同步中</div>
        </Card>
        <Card variant="metric" weight="secondary">
          <div className="card-label">数据源类型</div>
          <div className="card-value">{Object.keys(SOURCE_TYPE_META).length}</div>
          <div className="card-sub">支持的连接器类型</div>
        </Card>
        <Card variant="metric" weight="secondary">
          <div className="card-label">默认治理策略</div>
          <div className="card-value">自动</div>
          <div className="card-sub">高置信自动采纳</div>
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
              <Card key={type} variant="interactive" weight="tertiary">
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
              </Card>
            );
          })}
        </div>
      </div>

      {/* ── Registered Sources List ── */}
      {dataSources.length === 0 ? null : (
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
            <Button size="small" icon={<SyncOutlined />}>
              全部同步
            </Button>
          </div>
          <div style={{ display: "grid", gap: 0 }}>
            {dataSources.map((source) => {
              const meta = SOURCE_TYPE_META[source.source_type];
              const { display, iso } = formatTime(source.updated_at);
              const tone = STATUS_TONE[source.status] ?? "neutral";
              return (
                <Link
                  key={source.id}
                  href={`/data-sources/${source.id}`}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "40px 1.5fr 120px 140px 100px",
                    alignItems: "center",
                    gap: 12,
                    padding: "12px 20px",
                    borderBottom: "1px solid var(--line-light)",
                    textDecoration: "none",
                    color: "inherit",
                    transition: "background var(--transition-fast)",
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
                  <time
                    dateTime={iso}
                    title={iso}
                    style={{ fontSize: 12, color: "var(--text-muted)" }}
                  >
                    {display}
                  </time>
                  <StatusDot tone={tone}>{source.status}</StatusDot>
                </Link>
              );
            })}
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
