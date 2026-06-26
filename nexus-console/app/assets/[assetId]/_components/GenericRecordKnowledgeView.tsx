"use client";

/**
 * Generic record-type knowledge view — the fallback for record assets that
 * weren't classified into a known domain_profile (e.g. profile_detect
 * returned `generic_table.v1` or a custom downstream variant).
 *
 * Shows the asset's normalized_ref envelope metadata so the operator can
 * still confirm what was ingested even without a typed view. Workbook
 * locator / cell-level navigation is intentionally NOT supported here
 * (per B9 forbidden changes).
 */

import { Alert, Descriptions, Empty, Typography } from "antd";
import type { NormalizedAssetRef } from "@/lib/api";
import { formatDateTime } from "@/lib/api";

type Props = {
  normalizedRef: NormalizedAssetRef;
};

export function GenericRecordKnowledgeView({ normalizedRef }: Props) {
  const meta = normalizedRef.metadata_summary ?? {};
  const profile = typeof meta["domain_profile"] === "string"
    ? (meta["domain_profile"] as string)
    : "(未识别)";
  const recordType =
    typeof (meta["profile"] as Record<string, unknown> | null)?.["record_type"] === "string"
      ? ((meta["profile"] as Record<string, unknown>)["record_type"] as string)
      : null;

  return (
    <div className="flex flex-col gap-4">
      <Alert
        type="info"
        showIcon
        title="通用记录视图"
        description="该 record 资产未匹配到岗位需求 / 职业能力分析视图。下方仅展示标准化资产的概要信息，详细字段请查看血缘追溯 / 原文预览。"
      />

      <div className="card">
        <div className="card-header">
          <Typography.Title level={5} className="!mb-0">
            标准化资产概要
          </Typography.Title>
        </div>
        <div className="card-body">
          <Descriptions
            column={{ xs: 1, sm: 1, md: 2 }}
            size="small"
            colon={false}
            items={[
              { key: "type", label: "资产类型", children: normalizedRef.normalized_type },
              { key: "rt", label: "Record Type", children: recordType ?? "—" },
              { key: "dp", label: "Domain Profile", children: profile },
              {
                key: "rc", label: "记录数",
                children: normalizedRef.record_count,
              },
              { key: "sv", label: "Schema 版本", children: normalizedRef.schema_version },
              { key: "st", label: "状态", children: normalizedRef.status },
              {
                key: "ua", label: "更新时间",
                children: formatDateTime(normalizedRef.updated_at),
              },
              {
                key: "ca", label: "创建时间",
                children: formatDateTime(normalizedRef.created_at),
              },
            ]}
          />
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <Typography.Title level={5} className="!mb-0">
            质量摘要
          </Typography.Title>
        </div>
        <div className="card-body">
          <QualitySummary value={normalizedRef.metadata_summary?.["quality_flags"]} />
        </div>
      </div>
    </div>
  );
}

function QualitySummary({ value }: { value: unknown }) {
  if (!value || typeof value !== "object") {
    return <Empty description="暂无质量标记" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }
  const flags = Object.entries(value as Record<string, unknown>).filter(
    ([, v]) => v !== false && v != null,
  );
  if (flags.length === 0) {
    return <Empty description="暂无质量标记" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }
  return (
    <ul className="m-0 list-none pl-0">
      {flags.map(([key, val]) => (
        <li key={key} className="text-sm">
          <span className="text-muted mr-2">{key}:</span>
          <span>{String(val)}</span>
        </li>
      ))}
    </ul>
  );
}
