"use client";

import { Table, Button } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { GovernanceRun } from "../_lib/types";
import { getClassification, getLevel } from "../_lib/types";
import { DomainTag } from "./DomainTag";
import { LevelTag } from "./LevelTag";
import { AdoptionTag } from "./AdoptionTag";
import { formatTime } from "@/lib/format-time";

export function DecisionTrailTab({
  runs,
  onOpenTrail,
}: {
  runs: GovernanceRun[];
  onOpenTrail: (refId: string) => void;
}) {
  const decided = runs.filter(
    (r) =>
      r.adoption_status === "auto_adopted" ||
      r.adoption_status === "manually_adopted" ||
      r.adoption_status === "partially_adopted" ||
      r.adoption_status === "rejected",
  );

  const columns: ColumnsType<GovernanceRun> = [
    {
      title: "对象",
      dataIndex: "normalized_ref_id",
      render: (id: string) => (
        <span className="font-mono text-xs">{id.slice(0, 20)}&hellip;</span>
      ),
    },
    {
      title: "最终结果",
      render: (_: unknown, r: GovernanceRun) => (
        <span className="inline-flex gap-1">
          <DomainTag classification={getClassification(r)} />
          <LevelTag level={getLevel(r)} />
        </span>
      ),
    },
    {
      title: "达成方式",
      render: (_: unknown, r: GovernanceRun) => <AdoptionTag status={r.adoption_status} />,
      width: 120,
    },
    {
      title: "证据",
      render: (_: unknown, r: GovernanceRun) => (
        <span className="text-xs text-muted">
          {r.model_alias.split("/").pop()} &middot; {r.prompt_version}
        </span>
      ),
    },
    {
      title: "时间",
      dataIndex: "updated_at",
      width: 140,
      render: (t: string) => {
        const { display, iso } = formatTime(t);
        return (
          <time dateTime={iso} title={iso} className="text-xs text-secondary">
            {display}
          </time>
        );
      },
    },
    {
      title: "",
      width: 110,
      render: (_: unknown, r: GovernanceRun) => (
        <Button type="link" size="small" onClick={() => onOpenTrail(r.normalized_ref_id)}>
          决策追踪
        </Button>
      ),
    },
  ];

  return (
    <Table
      rowKey="id"
      dataSource={decided}
      columns={columns}
      size="middle"
      pagination={false}
      locale={{ emptyText: "暂无决策记录" }}
    />
  );
}
