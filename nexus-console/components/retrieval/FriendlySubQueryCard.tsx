"use client";

import { Alert, Space, Tag, Tooltip } from "antd";
import { Link2 } from "lucide-react";

import type {
  EvidenceStrength,
  FriendlyDisplayFilter,
  FriendlySubQueryCard as SubQueryCard,
  FriendlySubQueryResult,
  FriendlySubQueryStatus,
} from "@/lib/retrievalTypes";

interface FriendlySubQueryCardProps {
  card: SubQueryCard;
}

const STATUS_TAG: Record<
  FriendlySubQueryStatus,
  "default" | "processing" | "success" | "warning" | "error"
> = {
  pending: "default",
  running: "processing",
  completed: "success",
  blocked: "warning",
  degraded: "warning",
  failed: "error",
  skipped: "default",
};

const EVIDENCE_TAG: Record<EvidenceStrength, "success" | "warning" | "error"> = {
  strong: "success",
  medium: "warning",
  weak: "error",
};

export function FriendlySubQueryCard({ card }: FriendlySubQueryCardProps) {
  return (
    <div
      className="rounded-lg border border-line bg-surface p-4"
      data-testid="friendly-sub-query-card"
      data-query-id={card.query_id}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-base font-semibold text-brand">{card.display_index}</span>
        <span className="text-base font-medium text-gray-800">{card.title}</span>
        <Tag color={STATUS_TAG[card.status]}>{card.status_display}</Tag>
        {card.depends_on_display.length > 0 && (
          <span className="ml-auto inline-flex items-center gap-1 text-xs text-gray-500">
            <Link2 size={12} />
            {card.depends_on_display.join(" / ")}
          </span>
        )}
      </div>

      <div className="mb-3 grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
        <MetaLine label="目的" value={card.purpose_display} />
        <MetaLine label="通道" value={card.channel_display} />
        <MetaLine label="领域" value={card.domain_display} />
      </div>

      {card.filter_summary.length > 0 && (
        <FilterSummary filters={card.filter_summary} />
      )}

      {card.degraded_reasons.length > 0 && (
        <Alert
          type="warning"
          showIcon
          className="mt-3"
          title="降级原因"
          description={card.degraded_reasons.join("；")}
        />
      )}

      {card.result_summary && <ResultLine result={card.result_summary} />}
    </div>
  );
}

function MetaLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-1">
      <span className="text-gray-500">{label}</span>
      <span className="text-gray-700">·</span>
      <span className="text-gray-800">{value}</span>
    </div>
  );
}

function FilterSummary({ filters }: { filters: FriendlyDisplayFilter[] }) {
  return (
    <div>
      <div className="mb-1 text-xs text-gray-500">筛选条件</div>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {filters.map((f, idx) => (
          <li key={`${f.label}-${idx}`} className="flex flex-wrap items-center gap-2">
            <Tag color="geekblue">{f.label}</Tag>
            <Space size={4} wrap>
              {f.values.map((v) => (
                <Tag key={v} color="blue" className="!m-0">
                  {v}
                </Tag>
              ))}
            </Space>
            <span className="text-xs text-gray-500">{f.match_strategy_display}</span>
            {f.is_optional && (
              <Tooltip title="可选桶 —— 未命中不阻塞其他条件">
                <Tag color="orange">可选</Tag>
              </Tooltip>
            )}
            {f.is_from_binding && (
              <Tag color="purple">
                取自 {f.binding_source_display ?? "前置结果"}
              </Tag>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ResultLine({ result }: { result: FriendlySubQueryResult }) {
  return (
    <div
      className="mt-3 flex flex-wrap items-center gap-3 rounded-md bg-gray-50 p-3"
      data-testid="friendly-sub-query-result"
    >
      <span className="text-sm font-medium text-gray-700">{result.hit_count_display}</span>
      <span className="text-xs text-gray-500">·</span>
      <span className="text-xs text-gray-600">{result.duration_display}</span>
      {result.match_layer_summary && (
        <>
          <span className="text-xs text-gray-500">·</span>
          <span className="text-xs text-gray-600">{result.match_layer_summary}</span>
        </>
      )}
      <Tag color={EVIDENCE_TAG[result.evidence_strength]} className="ml-auto">
        {result.evidence_strength_display}
      </Tag>
      {result.warnings.length > 0 && (
        <div className="w-full text-xs text-orange-600">
          <span className="font-medium">警告：</span>
          {result.warnings.join("；")}
        </div>
      )}
    </div>
  );
}
