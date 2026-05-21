"use client";

import { Card as SharedCard } from "@/components/shared/Card";
import type { AssetStats } from "../_lib/types";

export function AssetsSummary({ stats }: { stats: AssetStats }) {
  return (
    <div className="metric-grid-4">
      <SharedCard variant="metric" weight="secondary" tone="success">
        <div className="card-label">available</div>
        <div className="card-value">{stats.available}</div>
        <div className="card-sub">可访问且可索引</div>
      </SharedCard>
      <SharedCard
        variant="metric"
        weight="secondary"
        tone={stats.reviewRequired > 0 ? "warning" : "default"}
      >
        <div className="card-label">review_required</div>
        <div className="card-value">{stats.reviewRequired}</div>
        <div className="card-sub">待复核资产</div>
      </SharedCard>
      <SharedCard variant="metric" weight="secondary">
        <div className="card-label">标准化引用</div>
        <div className="card-value">{stats.currentNormalizedRefs}</div>
        <div className="card-sub">current normalized refs</div>
      </SharedCard>
      <SharedCard
        variant="metric"
        weight="secondary"
        tone={stats.staleIndex > 0 ? "warning" : "default"}
      >
        <div className="card-label">stale index</div>
        <div className="card-value">{stats.staleIndex}</div>
        <div className="card-sub">需重建索引</div>
      </SharedCard>
    </div>
  );
}
