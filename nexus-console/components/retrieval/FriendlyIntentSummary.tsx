"use client";

import { Progress, Space, Tag } from "antd";
import { Sparkles } from "lucide-react";

import type {
  ConfidenceLevel,
  FriendlyIntentSummary as IntentSummary,
} from "@/lib/retrievalTypes";

interface FriendlyIntentSummaryProps {
  intent: IntentSummary;
}

const CONFIDENCE_META: Record<
  ConfidenceLevel,
  { color: "success" | "warning" | "error"; label: string }
> = {
  high: { color: "success", label: "高置信" },
  medium: { color: "warning", label: "中置信" },
  low: { color: "error", label: "低置信" },
};

export function FriendlyIntentSummary({ intent }: FriendlyIntentSummaryProps) {
  const meta = CONFIDENCE_META[intent.confidence_level];
  const confidencePct = Math.round(intent.confidence * 100);

  return (
    <div
      className="rounded-lg border border-line bg-surface p-4"
      data-testid="friendly-intent-summary"
    >
      <div className="mb-3 flex items-start gap-2">
        <Sparkles size={16} className="mt-1 shrink-0 text-brand" />
        <div className="flex-1">
          <div className="mb-1 text-sm font-medium text-gray-700">意图理解</div>
          <p className="m-0 text-sm leading-relaxed text-gray-800">
            {intent.natural_language}
          </p>
        </div>
        <Tag color={meta.color} className="shrink-0">
          {meta.label} · {confidencePct}%
        </Tag>
      </div>

      <Progress
        percent={confidencePct}
        size="small"
        showInfo={false}
        status={meta.color === "error" ? "exception" : undefined}
        className="mb-3"
      />

      {intent.business_domains_display.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span className="text-xs text-gray-500">领域</span>
          <Space size={4} wrap>
            {intent.business_domains_display.map((domain) => (
              <Tag key={domain} color="blue">
                {domain}
              </Tag>
            ))}
          </Space>
        </div>
      )}

      {intent.identified_constraints.length > 0 && (
        <div className="mb-3">
          <div className="mb-1 text-xs text-gray-500">识别到的约束</div>
          <ul className="m-0 flex list-none flex-col gap-1 p-0">
            {intent.identified_constraints.map((c) => (
              <li
                key={`${c.label}-${c.value}`}
                className="flex flex-wrap items-center gap-2 text-xs"
              >
                <Tag color="geekblue">{c.label}</Tag>
                <span className="font-medium text-gray-800">{c.value}</span>
                <span className="text-gray-400">·</span>
                <span className="text-gray-500">{c.source_display}</span>
                {c.confidence != null && (
                  <span className="text-gray-400">
                    · {Math.round(c.confidence * 100)}%
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {intent.unresolved_terms.length > 0 && (
        <div className="mb-3">
          <div className="mb-1 text-xs text-gray-500">尚未消化的词</div>
          <Space size={4} wrap>
            {intent.unresolved_terms.map((term) => (
              <Tag key={term} color="default">
                {term}
              </Tag>
            ))}
          </Space>
        </div>
      )}

      {intent.clarification_suggestions.length > 0 && (
        <div className="rounded-md bg-yellow-50 p-3">
          <div className="mb-1 text-xs font-medium text-yellow-800">
            建议进一步澄清
          </div>
          <ul className="m-0 flex list-disc flex-col gap-1 pl-5 text-xs text-yellow-700">
            {intent.clarification_suggestions.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
