"use client";

import { Table, Button } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { GovernanceRun } from "../_lib/types";
import { getClassification, getLevel, getConfidence, getOrgScope } from "../_lib/types";
import { DomainTag } from "./DomainTag";
import { LevelTag } from "./LevelTag";
import { ConfidenceTag } from "./ConfidenceTag";
import { AdoptionTag } from "./AdoptionTag";

export function AiSuggestionsTab({
  runs,
  onViewDetail,
}: {
  runs: GovernanceRun[];
  onViewDetail: (r: GovernanceRun) => void;
}) {
  const filtered = runs.filter(
    (r) => r.validation_status === "schema_valid" && getConfidence(r) >= 0.6,
  );

  const columns: ColumnsType<GovernanceRun> = [
    {
      title: "资产",
      dataIndex: "normalized_ref_id",
      render: (id: string) => (
        <span className="font-semibold font-mono text-xs">{id.slice(0, 20)}&hellip;</span>
      ),
    },
    {
      title: "AI 建议",
      render: (_: unknown, r: GovernanceRun) => (
        <span className="inline-flex items-center gap-1">
          <DomainTag classification={getClassification(r)} />
          <LevelTag level={getLevel(r)} />
          <span className="text-xs text-secondary">{getOrgScope(r)}</span>
        </span>
      ),
    },
    {
      title: "置信度",
      render: (_: unknown, r: GovernanceRun) => <ConfidenceTag confidence={getConfidence(r)} />,
      width: 110,
    },
    {
      title: "采纳状态",
      render: (_: unknown, r: GovernanceRun) => <AdoptionTag status={r.adoption_status} />,
      width: 120,
    },
    {
      title: "规则结果",
      render: (_: unknown, r: GovernanceRun) => (
        <span className="text-xs text-secondary">
          {r.validation_status === "schema_valid" ? "校验通过" : r.validation_status}
        </span>
      ),
      width: 120,
    },
    {
      title: "",
      width: 60,
      render: (_: unknown, r: GovernanceRun) => (
        <Button type="link" size="small" onClick={() => onViewDetail(r)}>
          详情
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
      pagination={{
        pageSize: 10,
        showSizeChanger: true,
        pageSizeOptions: ["10", "20", "50"],
        showTotal: (total, range) => range[0] + "-" + range[1] + " / " + total + " 条",
      }}
      locale={{ emptyText: "暂无 AI 建议" }}
    />
  );
}
