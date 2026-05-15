type ProgressBarProps = {
  value: number; // 0-100
  variant?: "default" | "success" | "warning";
  showLabel?: boolean;
};

export function ProgressBar({ value, variant = "default", showLabel = false }: ProgressBarProps) {
  const pct = Math.min(100, Math.max(0, value));
  const fillClass = variant === "success" ? "success" : variant === "warning" ? "warning" : "";

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
      <div className="progress-bar" style={{ flex: 1 }}>
        <div
          className={`progress-bar-fill ${fillClass}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {showLabel && (
        <span className="text-xs text-muted" style={{ minWidth: 36, textAlign: "right" }}>
          {pct}%
        </span>
      )}
    </div>
  );
}
