/**
 * AI confidence tier badge matching v3.2 three-color system:
 *   high   >= 85%  → green, "高置信度"
 *   mid    60-84%  → amber, "中等置信度"
 *   low    < 60%   → red,   "低置信度"
 */
type ConfidenceBadgeProps = {
  confidence: number; // 0-1 or 0-100, auto-detected
  showValue?: boolean;
};

function normalize(value: number): number {
  return value > 1 ? value / 100 : value;
}

function tier(value: number): { label: string; variant: "confidence-high" | "confidence-mid" | "confidence-low" } {
  const n = normalize(value);
  if (n >= 0.85) return { label: "高置信度", variant: "confidence-high" };
  if (n >= 0.6) return { label: "中等置信度", variant: "confidence-mid" };
  return { label: "低置信度", variant: "confidence-low" };
}

export function ConfidenceBadge({ confidence, showValue = true }: ConfidenceBadgeProps) {
  const t = tier(confidence);
  const pct = Math.round(normalize(confidence) * 100);

  return (
    <span className={`tag tag-${t.variant}`}>
      {t.label}
      {showValue ? ` ${pct}%` : ""}
    </span>
  );
}
