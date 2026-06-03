"use client";

import { Card, Empty, Progress, Tag } from "antd";
import { StatusLabel } from "@/components/StatusLabel";
import type { AIGovernanceRun } from "@/lib/api";

type Props = {
  runs: AIGovernanceRun[];
};

export function QualityTab({ runs }: Props) {
  const runWithQuality = runs.find((r) => r.quality_summary !== null);

  if (!runWithQuality?.quality_summary) {
    return (
      <Empty description="暂无质量评分 — AI 治理执行完成后，质量评分摘要将显示在此处" />
    );
  }

  const qs = runWithQuality.quality_summary;
  const dimScores = (qs.dimension_scores as Record<string, number>) ?? {};
  const checkItems = Array.isArray(qs.check_items)
    ? (qs.check_items as Record<string, unknown>[])
    : [];
  const blockingReasons = Array.isArray(qs.blocking_reasons)
    ? (qs.blocking_reasons as string[])
    : [];
  const qualityScore = qs.quality_score as number;
  const qualityLevel = qs.quality_level as string;

  const scoreColor =
    qualityScore >= 80
      ? "var(--success)"
      : qualityScore >= 60
        ? "var(--warning)"
        : "var(--error)";

  return (
    <div className="grid gap-4">
      {/* Score overview */}
      <Card
        title="综合质量评分"
        extra={<StatusLabel value={qualityLevel} />}
      >
        <div className="flex items-center gap-4 mb-4">
          <span className="text-5xl font-bold" style={{ color: scoreColor }}>
            {qualityScore.toFixed(0)}
          </span>
          <div>
            <div className="text-sm text-muted">满分 100</div>
            <div className="text-sm text-muted">
              置信度 {((qs.confidence as number ?? 0) * 100).toFixed(0)}%
            </div>
          </div>
        </div>

        {/* Dimension scores */}
        {Object.keys(dimScores).length > 0 && (
          <div className="flex flex-col gap-2">
            {Object.entries(dimScores).map(([dim, score]) => (
              <div key={dim} className="flex items-center gap-3">
                <span className="w-20 text-detail text-muted shrink-0">{dim}</span>
                <Progress
                  percent={score}
                  strokeColor={
                    score >= 80
                      ? "var(--success)"
                      : score >= 60
                        ? "var(--warning)"
                        : undefined
                  }
                  size="small"
                  className="flex-1"
                />
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Blocking reasons */}
      {blockingReasons.length > 0 && (
        <Card
          title="阻断原因"
          extra={<Tag color="error">{blockingReasons.length} 条</Tag>}
        >
          {blockingReasons.map((r, i) => (
            <div key={i} className="text-detail text-[var(--danger-600)] mb-1">
              {r}
            </div>
          ))}
        </Card>
      )}

      {/* Check items */}
      {checkItems.length > 0 && (
        <Card title="检查项明细" styles={{ body: { padding: 0 } }}>
          {checkItems.map((item, i) => {
            const status = String(item.status);
            const icon = status === "pass" ? "✓" : status === "fail" ? "✗" : "⚠";
            const color =
              status === "pass"
                ? "var(--success)"
                : status === "fail"
                  ? "var(--danger-600)"
                  : "var(--warning)";
            return (
              <div
                key={i}
                className="grid grid-cols-[24px_160px_1fr_80px] items-center p-3 border-b border-[var(--line)] last:border-b-0"
              >
                <span className="font-bold" style={{ color }}>{icon}</span>
                <span className="text-sm">{String(item.check_name)}</span>
                <span className="text-sm text-muted">{String(item.message)}</span>
                <span className="text-xs text-muted">{String(item.severity)}</span>
              </div>
            );
          })}
        </Card>
      )}
    </div>
  );
}
