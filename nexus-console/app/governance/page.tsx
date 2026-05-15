"use client";

import { useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { GovernanceQueue } from "@/components/GovernanceQueue";
import type { GovernanceQueueItem } from "@/components/GovernanceQueue";

// -- Demo / mock data for v3.2 governance center --
const mockItems: GovernanceQueueItem[] = [
  {
    id: "g1",
    assetTitle: "电子商务基础（第3版）",
    domain: "D4",
    level: "L2",
    confidence: 0.94,
    aiSuggestion: "自动分类为 D4 产教融合 · 教材",
    ruleMatches: ["教材识别", "默认公开"],
    qualityScore: 92,
    status: "auto_adopted",
    sla: "normal"
  },
  {
    id: "g2",
    assetTitle: "人才培养方案2025",
    domain: "D2",
    level: "L2",
    confidence: 0.82,
    aiSuggestion: "D2 人才培养 · 方案文档",
    ruleMatches: ["培养方案识别"],
    qualityScore: 85,
    status: "review_required",
    sla: "today"
  },
  {
    id: "g3",
    assetTitle: "内部竞标决策纪要",
    domain: "D6",
    level: "L4",
    confidence: 0.58,
    aiSuggestion: "检测到高敏关键词，建议 L4 并强制复核",
    ruleMatches: ["高敏关键词升级"],
    qualityScore: 65,
    status: "pending_review",
    sla: "overdue"
  },
  {
    id: "g4",
    assetTitle: "产教融合案例集",
    domain: "D4",
    level: "L3",
    confidence: 0.72,
    aiSuggestion: "D4 产教融合 · 案例汇编",
    ruleMatches: ["案例识别", "中敏升级"],
    qualityScore: 78,
    status: "overridden",
    sla: "normal"
  },
  {
    id: "g5",
    assetTitle: "政策法规汇编2025",
    domain: "D5",
    level: "L1",
    confidence: 0.96,
    aiSuggestion: "D5 政策法规 · 汇编",
    ruleMatches: ["法规识别", "默认公开"],
    qualityScore: 90,
    status: "auto_adopted",
    sla: "normal"
  },
  {
    id: "g6",
    assetTitle: "科研项目申报指南",
    domain: "D3",
    level: "L2",
    confidence: 0.88,
    aiSuggestion: "D3 科研数据 · 申报材料",
    ruleMatches: ["科研识别"],
    qualityScore: 82,
    status: "review_required",
    sla: "today"
  }
];

export default function GovernancePage() {
  const [items, setItems] = useState<GovernanceQueueItem[]>(mockItems);

  function handleAdopt(id: string) {
    setItems((prev) =>
      prev.map((item) =>
        item.id === id ? { ...item, status: "auto_adopted" as const } : item
      )
    );
  }

  function handleReject(id: string) {
    setItems((prev) =>
      prev.map((item) =>
        item.id === id ? { ...item, status: "rejected" as const } : item
      )
    );
  }

  function handleBulkAdopt(ids: string[]) {
    setItems((prev) =>
      prev.map((item) =>
        ids.includes(item.id) ? { ...item, status: "auto_adopted" as const } : item
      )
    );
  }

  return (
    <>
      <PageHeader
        prototypeId="NX-08"
        title="治理中心"
        description="AI 治理建议、质量评分、治理待办、规则执行追踪和决策记录。按队列分类管理，支持批量采纳和逐条裁定。"
        actions={
          <button className="btn btn-secondary">
            📋 导出决策报告
          </button>
        }
      />

      <GovernanceQueue
        items={items}
        onAdopt={handleAdopt}
        onReject={handleReject}
        onBulkAdopt={handleBulkAdopt}
      />
    </>
  );
}
