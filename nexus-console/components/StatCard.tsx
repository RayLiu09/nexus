import type { ReactNode } from "react";

type StatCardProps = {
  label: string;
  value: string | number;
  delta?: string;
  deltaTone?: "up" | "down";
  icon?: ReactNode;
  variant?: "default" | "brand" | "success" | "warning" | "danger";
};

export function StatCard({ label, value, delta, deltaTone, icon, variant = "default" }: StatCardProps) {
  return (
    <div className={`stat-card stat-card-${variant}`}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <span className="stat-card-label">{label}</span>
        {icon}
      </div>
      <span className="stat-card-value">{value}</span>
      {delta && (
        <span className={`stat-card-delta ${deltaTone === "down" ? "down" : "up"}`}>
          {deltaTone === "down" ? "↓" : "↑"} {delta}
        </span>
      )}
    </div>
  );
}
