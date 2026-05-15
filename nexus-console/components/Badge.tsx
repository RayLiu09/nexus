type BadgeVariant =
  | "neutral"
  | "brand"
  | "success"
  | "warning"
  | "danger"
  | "info"
  | "domain-d1" | "domain-d2" | "domain-d3" | "domain-d4" | "domain-d5" | "domain-d6"
  | "confidence-high" | "confidence-mid" | "confidence-low";

type BadgeProps = {
  label: string;
  variant?: BadgeVariant;
  className?: string;
};

const variantClass: Record<BadgeVariant, string> = {
  neutral: "tag",
  brand: "tag",
  success: "tag",
  warning: "tag",
  danger: "tag",
  info: "tag",
  "domain-d1": "tag tag-domain-d1",
  "domain-d2": "tag tag-domain-d2",
  "domain-d3": "tag tag-domain-d3",
  "domain-d4": "tag tag-domain-d4",
  "domain-d5": "tag tag-domain-d5",
  "domain-d6": "tag tag-domain-d6",
  "confidence-high": "tag tag-confidence-high",
  "confidence-mid": "tag tag-confidence-mid",
  "confidence-low": "tag tag-confidence-low"
};

const variantStyle: Record<string, React.CSSProperties> = {
  neutral: {},
  brand: { background: "var(--brand-50)", color: "var(--brand-700)" },
  success: { background: "var(--success-bg)", color: "var(--success-text)" },
  warning: { background: "var(--warning-bg)", color: "var(--warning-text)" },
  danger: { background: "var(--danger-bg)", color: "var(--danger-text)" },
  info: { background: "var(--info-bg)", color: "var(--info-text)" }
};

export function Badge({ label, variant = "neutral", className }: BadgeProps) {
  const cls = variantClass[variant] ?? "tag";
  const style = variantStyle[variant];

  return (
    <span className={`${cls} ${className ?? ""}`} style={style}>
      {label}
    </span>
  );
}
