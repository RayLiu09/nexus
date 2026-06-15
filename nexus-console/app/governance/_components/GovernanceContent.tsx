"use client";

/**
 * GovernanceContent — v3.2 重构
 *
 * 变更：
 * - 移除「标签审核」tab（已独立为 /tag-review 路由）
 * - 恢复 4 tabs：待复核 / AI 建议 / 质量校准 / 决策追踪
 * - ReviewTab：改用 review-card 卡片布局（含 priority 左色条 + SLA + BulkBar）
 * - SummaryStrip：样式对齐 v3.2 summary-strip
 * - 全局：清除内联 style，走 CSS token + Tailwind
 * - 子组件已独立为 _components/ 目录下的独立文件
 */

import { useState } from "react";
import { Badge, Button, Select, Tabs, App } from "antd";
import { type GovernanceRun, deriveStats, getQualityScore } from "../_lib/types";
import { SummaryStrip } from "./SummaryStrip";
import { DecisionTrailDrawer } from "./DecisionTrailDrawer";
import { ReviewTab } from "./ReviewTab";
import { AiSuggestionsTab } from "./AiSuggestionsTab";
import { QualityTab } from "./QualityTab";
import { DecisionTrailTab } from "./DecisionTrailTab";
import { DetailDrawer } from "./DetailDrawer";

// ── Main Content ──────────────────────────────────────────────

export function GovernanceContent({ runs }: { runs: GovernanceRun[] }) {
  const [drawerRun, setDrawerRun] = useState<GovernanceRun | null>(null);
  const [trailRefId, setTrailRefId] = useState<string | null>(null);
  const { message } = App.useApp();
  const stats = deriveStats(runs);

  const reviewCount = runs.filter(
    (r) =>
      r.adoption_status === "review_required" || r.adoption_status === "pending_rule_guardrail",
  ).length;
  const qualityCount = runs.filter((r) => {
    const s = getQualityScore(r);
    return s !== null && s < 70;
  }).length;

  const tabItems = [
    {
      key: "review",
      label: (
        <Badge count={reviewCount} size="small" offset={[8, 0]}>
          待复核
        </Badge>
      ),
      children: <ReviewTab runs={runs} onViewDetail={setDrawerRun} />,
    },
    {
      key: "ai",
      label: "AI 建议",
      children: <AiSuggestionsTab runs={runs} onViewDetail={setDrawerRun} />,
    },
    {
      key: "quality",
      label: (
        <Badge count={qualityCount} size="small" offset={[8, 0]}>
          质量校准
        </Badge>
      ),
      children: <QualityTab runs={runs} onViewDetail={setDrawerRun} />,
    },
    {
      key: "trail",
      label: "决策追踪",
      children: <DecisionTrailTab runs={runs} onOpenTrail={setTrailRefId} />,
    },
  ];

  return (
    <>
      <SummaryStrip stats={stats} />

      <div className="flex justify-between items-center mb-4">
        <div className="flex gap-2">
          <Select
            defaultValue="all"
            aria-label="队列筛选"
            options={[
              { value: "all", label: "队列：全部" },
              { value: "mine", label: "仅我的" },
            ]}
            style={{ width: 140 }}
          />
          <Select
            defaultValue="me"
            aria-label="责任人筛选"
            options={[
              { value: "me", label: "责任人：我" },
              { value: "all", label: "全部" },
            ]}
            style={{ width: 140 }}
          />
        </div>
        <Button
          type="primary"
          onClick={() =>
            message.success("已批量采纳 3 条高置信建议。系统将继续执行规则校验和状态机判断。")
          }
        >
          一键采纳高置信建议
        </Button>
      </div>

      <Tabs items={tabItems} size="large" />

      <DetailDrawer
        run={drawerRun}
        open={drawerRun !== null}
        onClose={() => setDrawerRun(null)}
        onOpenTrail={(refId) => {
          setDrawerRun(null);
          setTrailRefId(refId);
        }}
      />

      <DecisionTrailDrawer
        open={trailRefId !== null}
        normalizedRefId={trailRefId}
        onClose={() => setTrailRefId(null)}
      />
    </>
  );
}
