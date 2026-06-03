"use client";

import { slaTier, formatSla } from "@/lib/format-time";

export function SlaTimer({ deadline }: { deadline: string }) {
  const tier = slaTier(deadline);
  const label = formatSla(deadline);
  const color =
    tier === "overdue"
      ? "var(--danger-600)"
      : tier === "today"
        ? "var(--warning-600)"
        : "var(--text-secondary)";
  return (
    <span role="status" aria-label={`SLA: ${label}`} className="text-xs font-semibold" style={{ color }}>
      {label}
    </span>
  );
}
