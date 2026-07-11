"use client";

import { Card, Empty, Tag, Tooltip } from "antd";
import { AlertTriangle, Info } from "lucide-react";

/**
 * M-C v1.3 known warning-code catalog. Codes not listed here are shown
 * as-is with a generic "info" style. Text mirrors the retrieval
 * spec + PR-9/10/13 audit strings; keep in sync when new codes land.
 */
const WARNING_CATALOG: Record<string, { tone: "warning" | "info"; description: string }> = {
  tag_target_type_not_configured: {
    tone: "warning",
    description:
      "查询用到了 tag_filter，但 query_profile 未声明 tag_target_type — Phase A 无法收窄，回退到不过滤。",
  },
  outline_chunk_lift_empty: {
    tone: "warning",
    description:
      "task_outline_context 命中了 outline_node，但 knowledge_chunk 反查为空 — 空集短路。可能是章节尚未切片。",
  },
  weighted_rerank_applied: {
    tone: "info",
    description: "PR-13 WEIGHTED combine op 已生效，records 按 target_scores 汇总重排。",
  },
  optional_bucket_empty: {
    tone: "info",
    description: "某个 optional=true 的 tag 桶未命中，已从 combine 中丢弃而不 collapse 整个 AND。",
  },
  tag_filter_resolver_error: {
    tone: "warning",
    description: "Phase A tag resolver 抛错（bucket 桶格式非法）— 视为空 bucket 处理。",
  },
  tag_filter_bucket_out_of_domain: {
    tone: "warning",
    description:
      "查询桶名不在 query_profile.allowed_tag_types 里 — sql_guardrails 已拦截，仅作提示。",
  },
  layer_l2_not_implemented: {
    tone: "info",
    description: "调用侧要求 L2（别名字典）匹配，但目前尚未落地；已跳过。",
  },
  layer_l3_not_implemented: {
    tone: "info",
    description: "调用侧要求 L3（标准 code）匹配，但目前尚未落地；已跳过。",
  },
  layer_l5_chunk_fallback_out_of_scope: {
    tone: "info",
    description: "L5 chunk-level 语义回退被显式关闭；只走 L1/L1.5/L4。",
  },
};

interface WarningsPanelProps {
  warnings: string[];
}

export function WarningsPanel({ warnings }: WarningsPanelProps) {
  return (
    <Card
      size="small"
      title={
        <span className="inline-flex items-center gap-2">
          <AlertTriangle size={16} className="text-warning" />
          告警与提示 ({warnings.length})
        </span>
      }
    >
      {warnings.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="本次执行未产生告警"
        />
      ) : (
        <ul className="flex list-none flex-col gap-2 p-0">
          {warnings.map((code, idx) => {
            const meta = WARNING_CATALOG[extractCode(code)];
            const tone = meta?.tone ?? "info";
            const desc = meta?.description;
            return (
              <li key={`${code}-${idx}`} className="flex items-start gap-2">
                <Tag color={tone === "warning" ? "orange" : "blue"} className="mt-0.5">
                  {code}
                </Tag>
                {desc && (
                  <Tooltip title={desc}>
                    <Info size={14} className="mt-1 shrink-0 text-gray-400" />
                  </Tooltip>
                )}
                {desc && <span className="text-xs text-gray-600">{desc}</span>}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

/**
 * Codes sometimes carry inline detail after a `:` (e.g.
 * `tag_filter_resolver_error:regions:bucket_out_of_domain`).
 * Look up the catalog by the head token.
 */
function extractCode(raw: string): string {
  const idx = raw.indexOf(":");
  return idx === -1 ? raw : raw.slice(0, idx);
}
