"use client";

import { useState } from "react";
import Link from "next/link";
import { Button, Card, Statistic, Tag } from "antd";
import { StatusLabel } from "@/components/StatusLabel";
import { EmptyState } from "@/components/shared/EmptyState";
import { formatTime } from "@/lib/format-time";
import { shortId, type AIGovernanceRun, type AuditLog } from "@/lib/api";

type SlaCategory = "overdue" | "today" | "normal";

function categorizeSla(createdAt: string): SlaCategory {
  const created = new Date(createdAt).getTime();
  const now = Date.now();
  const hoursSince = (now - created) / (1000 * 60 * 60);
  if (hoursSince > 48) return "overdue";
  if (hoursSince > 24) return "today";
  return "normal";
}

const SLA_STATUS_VALUE: Record<SlaCategory, string> = {
  overdue: "review_required",
  today: "pending",
  normal: "available",
};

const SLA_STYLE: Record<SlaCategory, { border: string; bg: string; label: string; color: string }> =
  {
    overdue: {
      border: "var(--danger-500)",
      bg: "var(--danger-50)",
      label: "超时",
      color: "var(--danger-700)",
    },
    today: {
      border: "var(--warning-500)",
      bg: "var(--warning-50)",
      label: "今日",
      color: "var(--warning-700)",
    },
    normal: { border: "transparent", bg: "transparent", label: "正常", color: "var(--text-muted)" },
  };

export function WorkspaceContent({
  pendingReview,
  recentAudits,
}: {
  pendingReview: AIGovernanceRun[];
  recentAudits: AuditLog[];
}) {
  const [filter, setFilter] = useState<SlaCategory | "all">("all");

  const itemsWithSla = pendingReview.map((r) => ({
    ...r,
    sla: categorizeSla(r.created_at),
  }));

  const overdueCount = itemsWithSla.filter((i) => i.sla === "overdue").length;
  const todayCount = itemsWithSla.filter((i) => i.sla === "today").length;
  const normalCount = itemsWithSla.filter((i) => i.sla === "normal").length;

  const filtered = filter === "all" ? itemsWithSla : itemsWithSla.filter((i) => i.sla === filter);

  return (
    <>
      {/* ── SLA Metrics ── */}
      <div className="metric-grid-4">
        <Card size="small" className="metric-secondary">
          <Statistic
            title="超时"
            value={overdueCount}
            valueStyle={overdueCount > 0 ? { color: "var(--danger-600)" } : undefined}
          />
          <div className="text-text-muted mt-1 text-xs">&gt;48h 未处理</div>
        </Card>
        <Card size="small" className="metric-secondary">
          <Statistic
            title="今日待处理"
            value={todayCount}
            valueStyle={todayCount > 0 ? { color: "var(--warning-600)" } : undefined}
          />
          <div className="text-text-muted mt-1 text-xs">24-48h</div>
        </Card>
        <Card size="small" className="metric-secondary">
          <Statistic title="正常" value={normalCount} />
          <div className="text-text-muted mt-1 text-xs">&lt;24h</div>
        </Card>
        <Card size="small" className="metric-secondary">
          <Statistic title="总计待办" value={pendingReview.length} />
          <div className="text-text-muted mt-1 text-xs">需复核治理项</div>
        </Card>
      </div>

      {/* ── Main Grid ── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 2fr) minmax(280px, 1fr)",
          gap: 20,
          alignItems: "start",
        }}
      >
        {/* Left: Pending Tasks */}
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
            <div style={{ fontSize: 15, fontWeight: 600 }}>待办任务</div>
            <div style={{ display: "flex", gap: 6 }}>
              {(["all", "overdue", "today", "normal"] as const).map((f) => (
                <Button
                  key={f}
                  size="small"
                  type={filter === f ? "primary" : "default"}
                  onClick={() => setFilter(f)}
                >
                  {f === "all"
                    ? "全部"
                    : f === "overdue"
                      ? "超时"
                      : f === "today"
                        ? "今日"
                        : "正常"}
                </Button>
              ))}
            </div>
          </div>

          {filtered.length === 0 ? (
            <EmptyState
              title={pendingReview.length === 0 ? "暂无待办" : "无匹配任务"}
              hint={pendingReview.length === 0 ? "所有治理项已处理完毕" : "当前筛选条件下无匹配任务"}
              size="small"
            />
          ) : (
            <div style={{ display: "grid", gap: 0 }}>
              {filtered.map((item) => {
                const sla = SLA_STYLE[item.sla];
                const { display } = formatTime(item.created_at);
                const aiOutput = (item.ai_output ?? {}) as Record<string, unknown>;
                return (
                  <Link
                    key={item.id}
                    href="/governance"
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1.5fr 90px 90px 100px 80px",
                      gap: 12,
                      padding: "12px 20px",
                      borderBottom: "1px solid var(--line-light)",
                      borderLeft: `3px solid ${sla.border}`,
                      background: sla.bg,
                      textDecoration: "none",
                      color: "inherit",
                      alignItems: "center",
                      fontSize: 13,
                    }}
                  >
                    <div>
                      <code style={{ fontSize: 11, fontFamily: "var(--font-mono)" }}>
                        {item.normalized_ref_id.slice(0, 24)}…
                      </code>
                      {typeof aiOutput.classification === "string" && (
                        <Tag color="blue" style={{ marginLeft: 8, fontSize: 11 }}>
                          {aiOutput.classification}
                        </Tag>
                      )}
                    </div>
                    <StatusLabel value={item.adoption_status} />
                    <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{display}</span>
                    <span style={{ fontSize: 12 }}>{item.model_alias.split("/").pop()}</span>
                    <StatusLabel value={SLA_STATUS_VALUE[item.sla]} label={sla.label} />
                  </Link>
                );
              })}
            </div>
          )}
        </div>

        {/* Right: Recent Activity */}
        <div
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line)",
            borderRadius: "var(--radius-xl)",
            padding: 20,
          }}
        >
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 16 }}>最近操作</div>
          {recentAudits.length === 0 ? (
            <EmptyState title="暂无操作记录" size="small" />
          ) : (
            <div style={{ display: "grid", gap: 10 }}>
              {recentAudits.map((audit) => {
                const { display, iso } = formatTime(audit.created_at);
                return (
                  <div
                    key={audit.id}
                    style={{
                      padding: "8px 12px",
                      borderRadius: "var(--radius-md)",
                      border: "1px solid var(--line-light)",
                      fontSize: 12,
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        marginBottom: 4,
                      }}
                    >
                      <strong>{audit.event_type}</strong>
                      <time dateTime={iso} style={{ color: "var(--text-muted)" }}>
                        {display}
                      </time>
                    </div>
                    {audit.actor_id && (
                      <span style={{ color: "var(--text-secondary)" }}>
                        by{" "}
                        <code style={{ fontFamily: "var(--font-mono)" }}>
                          {shortId(audit.actor_id)}
                        </code>
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
