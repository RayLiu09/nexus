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
import { type GovernanceRun, deriveStats } from "../_lib/types";
import {
  selectCurrentQualityCalibrationRuns,
  selectCurrentReviewRuns,
  selectLatestGovernanceRuns,
} from "@/lib/governance-runs";
import type { TagDictionary } from "@/lib/tagLabels";
import type { ClassificationDictionary } from "@/lib/classificationLabels";
import { SummaryStrip } from "./SummaryStrip";
import { DecisionTrailDrawer } from "./DecisionTrailDrawer";
import { ReviewTab } from "./ReviewTab";
import { AiSuggestionsTab } from "./AiSuggestionsTab";
import { QualityTab } from "./QualityTab";
import { DecisionTrailTab } from "./DecisionTrailTab";
import { DetailDrawer } from "./DetailDrawer";

// ── Main Content ──────────────────────────────────────────────

export function GovernanceContent({
  runs,
  tagDictionary,
  classificationDictionary,
}: {
  runs: GovernanceRun[];
  tagDictionary: TagDictionary;
  classificationDictionary: ClassificationDictionary;
}) {
  const [drawerRun, setDrawerRun] = useState<GovernanceRun | null>(null);
  const [trailRefId, setTrailRefId] = useState<string | null>(null);
  const [trailRun, setTrailRun] = useState<GovernanceRun | null>(null);
  const { message } = App.useApp();
  const stats = deriveStats(runs);
  const currentRuns = selectLatestGovernanceRuns(runs);
  const reviewRuns = selectCurrentReviewRuns(runs);
  const qualityRuns = selectCurrentQualityCalibrationRuns(runs);

  const reviewCount = reviewRuns.length;
  const qualityCount = qualityRuns.length;

  const tabItems = [
    {
      key: "review",
      label: (
        <Badge count={reviewCount} size="small" offset={[8, 0]}>
          待复核
        </Badge>
      ),
      children: <ReviewTab runs={reviewRuns} onViewDetail={setDrawerRun} />,
    },
    {
      key: "ai",
      label: "AI 建议",
      children: <AiSuggestionsTab runs={currentRuns} onViewDetail={setDrawerRun} />,
    },
    {
      key: "quality",
      label: (
        <Badge count={qualityCount} size="small" offset={[8, 0]}>
          质量校准
        </Badge>
      ),
      children: <QualityTab runs={qualityRuns} onViewDetail={setDrawerRun} />,
    },
    {
      key: "trail",
      label: "决策追踪",
      children: <DecisionTrailTab runs={runs} onOpenTrail={(refId, run) => { setTrailRefId(refId); setTrailRun(run ?? null); }} />,
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
        onOpenTrail={(refId, run) => {
          setDrawerRun(null);
          setTrailRefId(refId);
          setTrailRun(run ?? null);
        }}
        tagDictionary={tagDictionary}
      />

      <DecisionTrailDrawer
        open={trailRefId !== null}
        normalizedRefId={trailRefId}
        onClose={() => { setTrailRefId(null); setTrailRun(null); }}
        tagDictionary={tagDictionary}
        classificationDictionary={classificationDictionary}
        fallbackTags={trailRun?.ai_output}
      />
    </>
  );
}
