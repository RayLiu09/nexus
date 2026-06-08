"use client";

import { Table, Button, Progress, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { GovernanceRun } from "../_lib/types";
import { getQualityScore, getQualityLevel } from "../_lib/types";

export function QualityTab({
  runs,
  onViewDetail,
}: {
  runs: GovernanceRun[];
  onViewDetail: (r: GovernanceRun) => void;
}) {
  const filtered = runs.filter((r) => {
    const score = getQualityScore(r);
    return score !== null && score < 70;
  });

  const columns: ColumnsType<GovernanceRun> = [
    {
      title: "资产",
      dataIndex: "normalized_ref_id",
      render: (id: string) => (
        <span className="font-mono text-xs">{id.slice(0, 20)}&hellip;</span>
      ),
    },
    {
      title: "综合分",
      render: (_: unknown, r: GovernanceRun) => {
        const score = getQualityScore(r) ?? 0;
        return (
          <Progress
            percent={score}
            size="small"
            status={score < 60 ? "exception" : "normal"}
            className="w-[120px]"
          />
        );
      },
      width: 160,
    },
    {
      title: "低分维度",
      render: (_: unknown, r: GovernanceRun) => {
        const dimScores = (r.quality_summary?.dimension_scores as Record<string, number>) ?? {};
        const lowDim = Object.entries(dimScores)
          .filter(([, v]) => v < 70)
          .map(([k]) => k)
          .join("、");
        return lowDim ? (
          <span className="text-xs text-warning">{lowDim}</span>
        ) : (
          <span className="text-muted">-</span>
        );
      },
    },
    {
      title: "质量等级",
      render: (_: unknown, r: GovernanceRun) => {
        const lv = getQualityLevel(r);
        return lv ? (
          <Tag color={lv === "pass" ? "success" : lv === "fail" ? "error" : "warning"}>{lv}</Tag>
        ) : (
          "-"
        );
      },
      width: 100,
    },
    {
      title: "修复建议",
      render: () => <span className="text-xs text-secondary">补齐目录层级并合并断裂切片</span>,
    },
    {
      title: "操作",
      width: 80,
      render: (_: unknown, r: GovernanceRun) => (
        <Button type="link" size="small" onClick={() => onViewDetail(r)}>
          校准
        </Button>
      ),
    },
  ];

  return (
    <Table
      rowKey="id"
      dataSource={filtered}
      columns={columns}
      size="middle"
      pagination={false}
      locale={{ emptyText: "暂无质量待审" }}
    />
  );
}
