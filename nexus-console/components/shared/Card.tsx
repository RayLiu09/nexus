"use client";

/**
 * A5 卡片体系收敛 + A8 视觉权重 3 级
 *
 * 替代散落的 `.profile-card` `.review-card` `.source-card` `.provider-card` `.hero-card` `.metric-card` `.audit-item` 等 8 种语义类。
 *
 * variant：
 *   - default      —— 通用容器
 *   - metric       —— metric-grid 中的小型指标卡（紧凑）
 *   - hero         —— hero-strip 中的大数字卡（强调）
 *   - interactive  —— 可点击卡片，含 hover 提升
 *
 * weight（A8）：
 *   - primary      —— 主任务区，p24 + shadow-md
 *   - secondary    —— 辅助区，p20 + shadow-sm（默认）
 *   - tertiary     —— 列表项，p16 + 无 shadow
 *
 * tone（hero / metric 用）：
 *   - default | warning | danger | success
 */

import type { ReactNode, HTMLAttributes } from "react";

export type CardVariant = "default" | "metric" | "hero" | "interactive";
export type CardWeight = "primary" | "secondary" | "tertiary";
export type CardTone = "default" | "warning" | "danger" | "success";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: CardVariant;
  weight?: CardWeight;
  tone?: CardTone;
  /** 卡片主标题（可选；用于 metric / hero variant） */
  label?: ReactNode;
  /** 大数字（仅 metric / hero） */
  value?: ReactNode;
  /** 副标题（仅 metric / hero） */
  sub?: ReactNode;
  /** 通用内容（default / interactive） */
  children?: ReactNode;
}

const variantClass: Record<CardVariant, string> = {
  default: "card",
  metric: "card card--metric",
  hero: "card card--hero",
  interactive: "card card--interactive",
};

const weightClass: Record<CardWeight, string> = {
  primary: "card--primary",
  secondary: "card--secondary",
  tertiary: "card--tertiary",
};

const toneClass: Record<CardTone, string> = {
  default: "",
  warning: "card--warning",
  danger: "card--danger",
  success: "card--success",
};

export function Card({
  variant = "default",
  weight = "secondary",
  tone = "default",
  label,
  value,
  sub,
  children,
  className,
  ...rest
}: CardProps) {
  const isMetric = variant === "metric" || variant === "hero";

  return (
    <div
      className={[variantClass[variant], weightClass[weight], toneClass[tone], className]
        .filter(Boolean)
        .join(" ")}
      {...rest}
    >
      {isMetric ? (
        <>
          {label ? <div className="card-label">{label}</div> : null}
          {value !== undefined ? <div className="card-value">{value}</div> : null}
          {sub ? <div className="card-sub">{sub}</div> : null}
          {children}
        </>
      ) : (
        children
      )}
    </div>
  );
}
