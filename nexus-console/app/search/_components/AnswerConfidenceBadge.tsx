/**
 * AnswerConfidenceBadge — QA answer confidence indicator.
 *
 * P0 contract: confidence is the max retrieval score across cited sources
 * (`answer_confidence`). When null we render an explicit empty-state badge
 * (per design decision #4) rather than hiding it — keeps the answer card
 * layout stable and signals to operators that no scored evidence exists.
 *
 * Tier colours mirror `components/ConfidenceBadge.tsx`:
 *   >= 0.85  high  → 高置信度 (green)
 *   >= 0.60  mid   → 中等置信度 (amber)
 *   <  0.60  low   → 低置信度 (red) + 警示 Tooltip
 */
import { ExclamationCircleOutlined } from "@ant-design/icons";
import { Space, Tooltip } from "antd";

export interface AnswerConfidenceBadgeProps {
  /** Backend value: max(sources[].score) or null when no scored sources. */
  confidence: number | null | undefined;
}

function tier(value: number): {
  label: string;
  variant: "confidence-high" | "confidence-mid" | "confidence-low";
  weak: boolean;
} {
  if (value >= 0.85) return { label: "高置信度", variant: "confidence-high", weak: false };
  if (value >= 0.6) return { label: "中等置信度", variant: "confidence-mid", weak: false };
  return { label: "低置信度", variant: "confidence-low", weak: true };
}

export function AnswerConfidenceBadge({ confidence }: AnswerConfidenceBadgeProps) {
  if (confidence === null || confidence === undefined) {
    return (
      <Tooltip title="该回答无评分来源，置信度无法计算">
        <span className="tag tag-confidence-mid" style={{ opacity: 0.5 }}>
          无置信度
        </span>
      </Tooltip>
    );
  }
  const t = tier(confidence);
  const pct = Math.round(confidence * 100);
  return (
    <Space size={6}>
      <span className={`tag tag-${t.variant}`}>
        {t.label} {pct}%
      </span>
      {t.weak && (
        <Tooltip title="来源证据较弱，建议人工核查">
          <ExclamationCircleOutlined
            aria-label="证据较弱"
            tabIndex={0}
            className="text-warning"
          />
        </Tooltip>
      )}
    </Space>
  );
}
