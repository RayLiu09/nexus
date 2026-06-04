"use client";

/**
 * Thin wrapper over antd/Card for metric/hero stat cards.
 *
 * This component is retained to avoid a full page-level rewrite of all 7
 * consumers. When individual pages are reworked to use antd/Card +
 * antd/Statistic directly, this file can be deleted.
 */

import type { ReactNode } from "react";
import { Card as AntdCard } from "antd";

export type CardVariant = "default" | "metric" | "hero" | "interactive";
export type CardWeight = "primary" | "secondary" | "tertiary";
export type CardTone = "default" | "warning" | "danger" | "success";

export interface CardProps {
  variant?: CardVariant;
  weight?: CardWeight;
  tone?: CardTone;
  label?: ReactNode;
  value?: ReactNode;
  sub?: ReactNode;
  children?: ReactNode;
  className?: string;
  style?: React.CSSProperties;
  id?: string;
}

const toneBorder: Record<CardTone, string | undefined> = {
  default: undefined,
  warning: "var(--warning-300)",
  danger: "var(--danger-300)",
  success: "var(--success-300)",
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
  style,
  id,
}: CardProps) {
  const isMetric = variant === "metric" || variant === "hero";

  return (
    <AntdCard
      size={weight === "primary" ? "default" : "small"}
      className={className}
      style={{
        ...(toneBorder[tone] ? { borderColor: toneBorder[tone] } : undefined),
        ...(variant === "hero" ? { fontSize: "1.25rem" } : undefined),
        ...(variant === "interactive" ? { cursor: "pointer" } : undefined),
        ...style,
      }}
      id={id}
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
    </AntdCard>
  );
}
