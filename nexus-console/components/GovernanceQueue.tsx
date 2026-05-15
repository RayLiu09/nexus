"use client";

import { useState } from "react";
import { Tabs } from "@/components/Tabs";
import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { DomainTag } from "@/components/DomainTag";
import { StatusLabel } from "@/components/StatusLabel";
import { ProgressBar } from "@/components/ProgressBar";

// -- Mock governance queue item type --
export type GovernanceQueueItem = {
  id: string;
  assetTitle: string;
  domain?: string;
  level?: string;
  confidence: number;
  aiSuggestion: string;
  ruleMatches: string[];
  qualityScore?: number;
  status: "auto_adopted" | "review_required" | "pending_review" | "overridden" | "rejected";
  sla?: "overdue" | "today" | "normal";
};

type GovernanceQueueProps = {
  items: GovernanceQueueItem[];
  /** Called when user clicks "adopt" on a single item */
  onAdopt?: (id: string) => void;
  /** Called when user clicks "reject" on a single item */
  onReject?: (id: string) => void;
  /** Called when user bulk-adopts selected items */
  onBulkAdopt?: (ids: string[]) => void;
};

const queueTabs = [
  { id: "review", label: "待复核", badgeTone: "danger" as const },
  { id: "quality", label: "质量待审", badgeTone: "warning" as const },
  { id: "ai-suggest", label: "AI建议" },
  { id: "decision-log", label: "决策追踪" }
];

function filterItems(items: GovernanceQueueItem[], tab: string): GovernanceQueueItem[] {
  switch (tab) {
    case "review":
      return items.filter((i) => i.status === "review_required" || i.status === "pending_review");
    case "quality":
      return items.filter((i) => i.qualityScore != null && i.qualityScore < 70);
    case "ai-suggest":
      return items.filter((i) => i.status === "auto_adopted" || i.confidence >= 0.6);
    case "decision-log":
      return items.filter((i) => i.status === "overridden" || i.status === "rejected");
    default:
      return items;
  }
}

export function GovernanceQueue({ items, onAdopt, onReject, onBulkAdopt }: GovernanceQueueProps) {
  const [activeTab, setActiveTab] = useState("review");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const filtered = filterItems(items, activeTab);

  // Update tab badges
  const tabs = queueTabs.map((t) => {
    const count = filterItems(items, t.id).length;
    return {
      ...t,
      badge: count > 0 ? count : undefined
    };
  });

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="card">
      <div className="card-header">
        <Tabs tabs={tabs} activeTab={activeTab} onTabChange={setActiveTab} />
        <div className="flex items-center gap-2">
          {selected.size > 0 && (
            <>
              <span className="text-xs text-muted">已选 {selected.size} 项</span>
              <button
                className="btn btn-primary btn-sm"
                onClick={() => {
                  onBulkAdopt?.(Array.from(selected));
                  setSelected(new Set());
                }}
              >
                批量采纳
              </button>
              <button className="btn btn-ghost btn-sm" onClick={() => setSelected(new Set())}>
                取消选择
              </button>
            </>
          )}
        </div>
      </div>

      <div className="card-body" style={{ padding: 0 }}>
        {filtered.length === 0 ? (
          <div className="empty-state">
            <span className="empty-state-icon">✓</span>
            <strong>此队列暂无项目</strong>
            <p>所有项目已处理完毕</p>
          </div>
        ) : (
          <div>
            {filtered.map((item) => {
              const isSelected = selected.has(item.id);
              return (
                <div
                  key={item.id}
                  className="table-row"
                  style={{
                    gridTemplateColumns: "40px 2fr 1fr 100px 100px 120px 120px",
                    background: item.sla === "overdue" ? "var(--danger-50)" : undefined
                  }}
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => toggleSelect(item.id)}
                    style={{ width: 16, height: 16 }}
                  />
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 14 }}>{item.assetTitle}</div>
                    <div className="flex gap-1" style={{ marginTop: 4 }}>
                      {item.domain && <DomainTag domain={item.domain} />}
                      {item.level && <span className="tag">{item.level}</span>}
                    </div>
                  </div>
                  <ConfidenceBadge confidence={item.confidence} />
                  <div className="text-sm text-muted truncate" title={item.aiSuggestion}>
                    {item.aiSuggestion}
                  </div>
                  <div className="flex gap-1 flex-wrap">
                    {item.ruleMatches.map((r) => (
                      <span key={r} className="tag">{r}</span>
                    ))}
                  </div>
                  {item.qualityScore != null ? (
                    <ProgressBar value={item.qualityScore} variant={item.qualityScore >= 80 ? "success" : item.qualityScore >= 60 ? "warning" : "default"} showLabel />
                  ) : (
                    <span className="text-muted text-sm">-</span>
                  )}
                  <div className="flex gap-1">
                    <StatusLabel value={item.status} />
                    {item.sla === "overdue" && (
                      <span className="tag" style={{ background: "var(--danger-50)", color: "var(--danger-600)", fontWeight: 700 }}>
                        超时
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
