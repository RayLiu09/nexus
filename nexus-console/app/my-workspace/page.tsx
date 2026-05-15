"use client";

import { useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { StatusLabel } from "@/components/StatusLabel";
import { DomainTag } from "@/components/DomainTag";
import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { EmptyState } from "@/components/EmptyState";
import { Tabs } from "@/components/Tabs";

// -- SLA-driven workspace items --
type WorkspaceItem = {
  id: string;
  title: string;
  type: string;
  domain?: string;
  level?: string;
  confidence?: number;
  sla: "overdue" | "today" | "normal";
  dueDate?: string;
  status: string;
};

const mockItems: WorkspaceItem[] = [
  { id: "w1", title: "内部竞标决策纪要 · 分级复核", type: "分级复核", domain: "D6", level: "L4", confidence: 0.58, sla: "overdue", dueDate: "2026-05-14", status: "review_required" },
  { id: "w2", title: "人才培养方案2025 · 域分类确认", type: "域分类", domain: "D2", level: "L2", confidence: 0.82, sla: "today", dueDate: "2026-05-15", status: "review_required" },
  { id: "w3", title: "科研项目申报指南 · 标签审核", type: "标签审核", domain: "D3", level: "L2", confidence: 0.88, sla: "today", dueDate: "2026-05-15", status: "review_required" },
  { id: "w4", title: "产教融合案例集 · 质量复核", type: "质量复核", domain: "D4", level: "L3", confidence: 0.72, sla: "normal", status: "pending_review" },
  { id: "w5", title: "电子商务基础 · AI 建议确认", type: "AI 建议", domain: "D4", level: "L2", confidence: 0.94, sla: "normal", status: "auto_adopted" }
];

const workspaceTabs = [
  { id: "overdue", label: "超时", badgeTone: "danger" as const },
  { id: "today", label: "今日", badgeTone: "warning" as const },
  { id: "normal", label: "正常" },
  { id: "all", label: "全部" }
];

export default function MyWorkspacePage() {
  const [activeTab, setActiveTab] = useState("overdue");

  const filtered = activeTab === "all"
    ? mockItems
    : mockItems.filter((i) => i.sla === activeTab);

  const tabs = workspaceTabs.map((t) => {
    const count = t.id === "all"
      ? mockItems.length
      : mockItems.filter((i) => i.sla === t.id).length;
    return { ...t, badge: count > 0 ? count : undefined };
  });

  return (
    <>
      <PageHeader
        prototypeId="NX-14"
        title="我的工作区"
        description="按 SLA 优先级管理个人待办任务。超时任务优先处理，今日任务及时完成，正常任务按序推进。"
      />

      {/* Workload overview */}
      <div className="stat-grid">
        <div className="stat-card" style={{ borderColor: "var(--danger-300)", background: "var(--danger-50)" }}>
          <span className="stat-card-label">超时</span>
          <span className="stat-card-value" style={{ color: "var(--danger-600)" }}>{mockItems.filter((i) => i.sla === "overdue").length}</span>
        </div>
        <div className="stat-card" style={{ borderColor: "var(--warning-300)", background: "var(--warning-50)" }}>
          <span className="stat-card-label">今日待处理</span>
          <span className="stat-card-value" style={{ color: "var(--warning-600)" }}>{mockItems.filter((i) => i.sla === "today").length}</span>
        </div>
        <div className="stat-card">
          <span className="stat-card-label">正常</span>
          <span className="stat-card-value">{mockItems.filter((i) => i.sla === "normal").length}</span>
        </div>
        <div className="stat-card">
          <span className="stat-card-label">总计</span>
          <span className="stat-card-value">{mockItems.length}</span>
        </div>
      </div>

      {/* SLA tabs + task list */}
      <div className="card">
        <div className="card-header">
          <Tabs tabs={tabs} activeTab={activeTab} onTabChange={setActiveTab} />
          <div className="flex gap-2">
            <button className="btn btn-primary btn-sm">批量处理</button>
          </div>
        </div>

        <div className="card-body" style={{ padding: 0 }}>
          {filtered.length === 0 ? (
            <EmptyState icon="♨" title="此队列暂无任务" description="所有任务已处理完毕" />
          ) : (
            filtered.map((item) => {
              const slaStyle = item.sla === "overdue"
                ? { borderLeft: "3px solid var(--danger-500)", background: "var(--danger-50)" }
                : item.sla === "today"
                  ? { borderLeft: "3px solid var(--warning-500)", background: "var(--warning-50)" }
                  : { borderLeft: "3px solid transparent" };

              return (
                <div
                  className="table-row clickable"
                  key={item.id}
                  style={{ gridTemplateColumns: "2fr 100px 120px 100px 120px 100px 120px", ...slaStyle }}
                >
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 14 }}>{item.title}</div>
                    <div className="flex gap-1" style={{ marginTop: 4 }}>
                      <span className="tag">{item.type}</span>
                      {item.domain && <DomainTag domain={item.domain} />}
                    </div>
                  </div>
                  {item.domain && <DomainTag domain={item.domain} />}
                  <span className="tag">{item.level ?? "-"}</span>
                  {item.confidence != null ? (
                    <ConfidenceBadge confidence={item.confidence} />
                  ) : (
                    <span className="text-muted text-sm">-</span>
                  )}
                  <StatusLabel value={item.status} />
                  <span className="text-sm text-muted">{item.dueDate ?? "-"}</span>
                  <div className="flex gap-1">
                    {item.sla === "overdue" && (
                      <span className="tag" style={{ background: "var(--danger-100)", color: "var(--danger-700)", fontWeight: 700 }}>
                        超时
                      </span>
                    )}
                    {item.sla === "today" && (
                      <span className="tag" style={{ background: "var(--warning-100)", color: "var(--warning-700)", fontWeight: 700 }}>
                        今日
                      </span>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </>
  );
}
