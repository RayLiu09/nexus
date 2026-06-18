"use client";

import { Table, Button, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { GovernanceRun } from "../_lib/types";
import { getClassification, getConfidence, getLevel, getQualityScore } from "../_lib/types";
import { DomainTag } from "./DomainTag";
import { LevelTag } from "./LevelTag";
import { AdoptionTag } from "./AdoptionTag";
import { AssetRefCell } from "./AssetRefCell";
import { formatTime } from "@/lib/format-time";

export function DecisionTrailTab({
  runs,
  onOpenTrail,
}: {
  runs: GovernanceRun[];
  onOpenTrail: (refId: string, run?: GovernanceRun) => void;
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
      render: (_: string, r: GovernanceRun) => (
        <AssetRefCell
          title={r.asset_title}
          assetId={r.asset_id}
          normalizedRefId={r.normalized_ref_id}
        />
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
      width: 180,
      render: (_: unknown, r: GovernanceRun) => {
        const conf = getConfidence(r);
        const quality = getQualityScore(r);
        const confPct = conf > 0 ? `${Math.round(conf * 100)}%` : null;
        const qualityPct = quality != null ? `${Math.round(quality)}` : null;
        return (
          <Tooltip title={`模型 ${r.model_alias} · Prompt ${r.prompt_version}`} placement="topLeft">
            <span className="inline-flex items-center gap-2 text-xs">
              {confPct ? (
                <span>
                  <span className="text-muted">置信度 </span>
                  <span className="text-primary font-mono">{confPct}</span>
                </span>
              ) : (
                <span className="text-muted">置信度 -</span>
              )}
              <span className="text-line">|</span>
              {qualityPct ? (
                <span>
                  <span className="text-muted">质量分 </span>
                  <span className="text-primary font-mono">{qualityPct}</span>
                </span>
              ) : (
                <span className="text-muted">质量分 -</span>
              )}
            </span>
          </Tooltip>
        );
      },
    },
    {
      title: "时间",
      dataIndex: "updated_at",
      width: 140,
      render: (t: string) => {
        const { display, iso } = formatTime(t);
        return (
          <time dateTime={iso} title={iso} className="text-secondary text-xs">
            {display}
          </time>
        );
      },
    },
    {
      title: "",
      width: 110,
      render: (_: unknown, r: GovernanceRun) => (
        <Button type="link" size="small" onClick={() => onOpenTrail(r.normalized_ref_id, r)}>
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
      pagination={{
        pageSize: 10,
        showSizeChanger: true,
        pageSizeOptions: ["10", "20", "50"],
        showTotal: (total, range) => range[0] + "-" + range[1] + " / " + total + " 条",
      }}
      locale={{ emptyText: "暂无决策记录" }}
    />
  );
}
