"use client";

import { Card, Statistic } from "antd";
import type { AssetStats } from "../_lib/types";

export function AssetsSummary({ stats }: { stats: AssetStats }) {
  return (
    <div className="metric-grid-4">
      <Card size="small" className="metric-secondary">
        <Statistic
          title="available"
          value={stats.available}
          valueStyle={{ color: "var(--success-600)" }}
        />
        <div className="text-text-muted mt-1 text-xs">可访问且可索引</div>
      </Card>
      <Card size="small" className="metric-secondary">
        <Statistic
          title="review_required"
          value={stats.reviewRequired}
          valueStyle={stats.reviewRequired > 0 ? { color: "var(--warning-600)" } : undefined}
        />
        <div className="text-text-muted mt-1 text-xs">待复核资产</div>
      </Card>
      <Card size="small" className="metric-secondary">
        <Statistic title="标准化引用" value={stats.currentNormalizedRefs} />
        <div className="text-text-muted mt-1 text-xs">current normalized refs</div>
      </Card>
      <Card size="small" className="metric-secondary">
        <Statistic
          title="stale index"
          value={stats.staleIndex}
          valueStyle={stats.staleIndex > 0 ? { color: "var(--warning-600)" } : undefined}
        />
        <div className="text-text-muted mt-1 text-xs">需重建索引</div>
      </Card>
    </div>
  );
}
