"use client";

import { Card, Statistic } from "antd";
import type { GovernanceStats } from "../_lib/types";

export function SummaryStrip({ stats }: { stats: GovernanceStats }) {
  return (
    <div className="governance-summary">
      <Card size="small" variant="borderless" style={{ background: "var(--bg-alt)" }}>
        <Statistic
          title="待人工复核"
          value={stats.pendingReview}
          valueStyle={stats.pendingReview > 0 ? { color: "var(--danger-600)" } : undefined}
        />
      </Card>
      <Card size="small" variant="borderless" style={{ background: "var(--bg-alt)" }}>
        <Statistic
          title="规则冲突"
          value={stats.ruleConflict}
          valueStyle={stats.ruleConflict > 0 ? { color: "var(--warning-600)" } : undefined}
        />
      </Card>
      <Card size="small" variant="borderless" style={{ background: "var(--bg-alt)" }}>
        <Statistic
          title="质量待审"
          value={stats.qualityPending}
          valueStyle={stats.qualityPending > 0 ? { color: "var(--warning-600)" } : undefined}
        />
      </Card>
      <Card size="small" variant="borderless" style={{ background: "var(--bg-alt)" }}>
        <Statistic
          title="高置信可采纳"
          value={stats.highConfidenceAdoptable}
          valueStyle={{ color: "var(--brand)" }}
        />
      </Card>
      <Card size="small" variant="borderless" style={{ background: "var(--bg-alt)" }}>
        <Statistic title="已完成决策" value={stats.completedDecisions} />
      </Card>
    </div>
  );
}
