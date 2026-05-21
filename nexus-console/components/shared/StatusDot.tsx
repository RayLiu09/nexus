"use client";

/**
 * 共享原子 — StatusDot
 *
 * 状态徽标：圆点 + 文字，确保颜色信号有 icon/text 双通道（A2 a11y）。
 *
 * 与 v3.2 原型 .status / .status-{success|info|warning|danger|neutral} 视觉一致。
 */

import type { ReactNode } from "react";

export type StatusTone = "success" | "info" | "warning" | "danger" | "neutral";

export interface StatusDotProps {
  tone: StatusTone;
  children: ReactNode;
  /** 屏幕阅读器额外说明，如"状态：available" */
  ariaLabel?: string;
  className?: string;
}

const toneVar: Record<StatusTone, { fg: string; bg: string }> = {
  success: { fg: "var(--success-700)", bg: "var(--success-bg)" },
  info: { fg: "var(--brand-700)", bg: "var(--brand-50)" },
  warning: { fg: "var(--warning-700)", bg: "var(--warning-bg)" },
  danger: { fg: "var(--danger-700)", bg: "var(--danger-bg)" },
  neutral: { fg: "var(--text-secondary)", bg: "var(--gray-100)" },
};

const dotColor: Record<StatusTone, string> = {
  success: "var(--success-600)",
  info: "var(--brand-600)",
  warning: "var(--warning-600)",
  danger: "var(--danger-600)",
  neutral: "var(--gray-400)",
};

export function StatusDot({ tone, children, ariaLabel, className }: StatusDotProps) {
  return (
    <span
      role="status"
      aria-label={ariaLabel ?? (typeof children === "string" ? `状态：${children}` : undefined)}
      className={className}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "2px 10px",
        borderRadius: 999,
        background: toneVar[tone].bg,
        color: toneVar[tone].fg,
        fontSize: 12,
        fontWeight: 600,
        whiteSpace: "nowrap",
      }}
    >
      <span
        aria-hidden="true"
        style={{
          width: 7,
          height: 7,
          borderRadius: "50%",
          background: dotColor[tone],
          flexShrink: 0,
        }}
      />
      {children}
    </span>
  );
}
