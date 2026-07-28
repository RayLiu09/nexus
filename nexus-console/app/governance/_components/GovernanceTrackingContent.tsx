"use client";

import { useState } from "react";
import { Alert, Button, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { AssetRefCell } from "./AssetRefCell";
import { DecisionTrailDrawer } from "./DecisionTrailDrawer";
import type { TagDictionary } from "@/lib/tagLabels";
import type { ClassificationDictionary } from "@/lib/classificationLabels";
import { classificationLabel } from "@/lib/classificationLabels";
import { levelLabel, type LevelDictionary } from "@/lib/levelLabels";
import { formatTime } from "@/lib/format-time";

export interface GovernanceTrace {
  governance_result_id: string;
  normalized_ref_id: string;
  asset_id: string | null;
  asset_title: string | null;
  classification: string | null;
  level: string | null;
  quality_summary: Record<string, unknown>;
  governance_status: string;
  index_admission: boolean;
  decision_mode: "auto_adopted" | "human_confirmed" | "human_overridden" | "review_required";
  review_decision_id: string | null;
  reviewer_id: string | null;
  reviewer_name: string | null;
  review_reason: string | null;
  created_at: string | null;
  updated_at: string | null;
}

const PAGE_SIZE = 20;

const MODE_META: Record<GovernanceTrace["decision_mode"], { label: string; color: string }> = {
  auto_adopted: { label: "自动采纳", color: "success" },
  human_confirmed: { label: "人工确认", color: "success" },
  human_overridden: { label: "人工调整", color: "processing" },
  review_required: { label: "待治理审核", color: "warning" },
};

export function GovernanceTrackingContent({
  initialRows,
  initialTotal,
  error,
  tagDictionary,
  classificationDictionary,
  levelDictionary,
}: {
  initialRows: GovernanceTrace[];
  initialTotal: number;
  error: string | null;
  tagDictionary: TagDictionary;
  classificationDictionary: ClassificationDictionary;
  levelDictionary: LevelDictionary;
}) {
  const [rows, setRows] = useState(initialRows);
  const [total, setTotal] = useState(initialTotal);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(error);
  const [selectedResultId, setSelectedResultId] = useState<string | null>(null);

  const loadPage = async (nextPage: number) => {
    setLoading(true);
    setLoadError(null);
    try {
      const response = await fetch(`/api/governance-traces?page=${nextPage}&pageSize=${PAGE_SIZE}`, { cache: "no-store" });
      const envelope = await response.json() as {
        data?: GovernanceTrace[];
        meta?: { total?: number };
        error?: { message?: string };
      };
      if (!response.ok || !envelope.data) throw new Error(envelope.error?.message ?? "无法加载治理追踪记录");
      setRows(envelope.data);
      setTotal(envelope.meta?.total ?? total);
      setPage(nextPage);
    } catch (cause) {
      setLoadError(cause instanceof Error ? cause.message : "无法加载治理追踪记录");
    } finally {
      setLoading(false);
    }
  };

  const columns: ColumnsType<GovernanceTrace> = [
    {
      title: "数据资产",
      render: (_value, row) => <AssetRefCell title={row.asset_title} assetId={row.asset_id} normalizedRefId={row.normalized_ref_id} />,
    },
    {
      title: "数据分类",
      dataIndex: "classification",
      width: 130,
      render: (value: string | null) => displayClassification(value, classificationDictionary),
    },
    {
      title: "数据分级",
      dataIndex: "level",
      width: 90,
      render: (value: string | null) => displayLevel(value, levelDictionary),
    },
    {
      title: "质量结论",
      width: 130,
      render: (_value, row) => {
        const level = typeof row.quality_summary.quality_level === "string" ? row.quality_summary.quality_level : "-";
        const score = typeof row.quality_summary.quality_score === "number" ? row.quality_summary.quality_score : null;
        return <span>{level}{score !== null ? ` ${Math.round(score)}分` : ""}</span>;
      },
    },
    {
      title: "决策方式",
      width: 120,
      render: (_value, row) => {
        const meta = MODE_META[row.decision_mode];
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
    {
      title: "治理状态",
      width: 110,
      render: (_value, row) => <Tag color={row.governance_status === "available" ? "success" : "warning"}>{row.governance_status === "available" ? "已生效" : "需审核"}</Tag>,
    },
    { title: "审核人", width: 120, render: (_value, row) => row.reviewer_name || "系统" },
    {
      title: "决策时间",
      dataIndex: "created_at",
      width: 160,
      render: (value: string | null) => value ? <time dateTime={value}>{formatTime(value).display}</time> : "-",
    },
    {
      title: "操作",
      width: 100,
      render: (_value, row) => <Button type="link" size="small" onClick={() => setSelectedResultId(row.governance_result_id)}>查看证据</Button>,
    },
  ];

  return <>
    {loadError && <Alert type="error" showIcon title="治理追踪记录加载失败" description={loadError} className="mb-4" />}
    <div className="content-panel">
      <Table
        rowKey="governance_result_id"
        dataSource={rows}
        columns={columns}
        loading={loading}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total,
          showSizeChanger: false,
          onChange: (nextPage) => void loadPage(nextPage),
          showTotal: (count, range) => `${range[0]}-${range[1]} / ${count} 条治理记录`,
        }}
        locale={{ emptyText: "暂无正式治理记录" }}
      />
    </div>
    <DecisionTrailDrawer
      open={selectedResultId !== null}
      governanceResultId={selectedResultId}
      onClose={() => setSelectedResultId(null)}
      tagDictionary={tagDictionary}
      classificationDictionary={classificationDictionary}
    />
  </>;
}

function displayClassification(value: string | null, dictionary: ClassificationDictionary): string {
  if (!value) return "未确定";
  const label = classificationLabel(value, dictionary);
  return label === value ? "未识别分类" : label;
}

function displayLevel(value: string | null, dictionary: LevelDictionary): string {
  if (!value) return "未确定";
  const label = levelLabel(value, dictionary);
  return label === value ? "未识别分级" : label;
}
