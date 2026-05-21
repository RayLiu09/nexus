"use client";

/**
 * A1 四态规范 — Loading
 *
 * 用法：
 *   <Loading />                       默认骨架
 *   <Loading rows={5} />              指定骨架行数
 *   <Loading variant="card" />        卡片骨架（用于 metric / hero / 大卡片占位）
 *   <Loading variant="table" />       表格骨架（含表头与行）
 *
 * 与 Antd Skeleton 的关系：底层封装，统一项目内动效与间距，避免每页自调。
 */

import { Skeleton } from "antd";

export type LoadingVariant = "default" | "card" | "table" | "list" | "page";

export interface LoadingProps {
  variant?: LoadingVariant;
  rows?: number;
  className?: string;
  /** 屏幕阅读器友好文本；默认"加载中" */
  ariaLabel?: string;
}

export function Loading({
  variant = "default",
  rows = 3,
  className,
  ariaLabel = "加载中",
}: LoadingProps) {
  if (variant === "card") {
    return (
      <div className={className} role="status" aria-live="polite" aria-label={ariaLabel}>
        <Skeleton active paragraph={{ rows: 2, width: ["60%", "40%"] }} title={{ width: "30%" }} />
      </div>
    );
  }

  if (variant === "table") {
    return (
      <div className={className} role="status" aria-live="polite" aria-label={ariaLabel}>
        <Skeleton.Button active block style={{ height: 36, marginBottom: 12 }} />
        <Skeleton active paragraph={{ rows }} title={false} />
      </div>
    );
  }

  if (variant === "list") {
    return (
      <div className={className} role="status" aria-live="polite" aria-label={ariaLabel}>
        <Skeleton active paragraph={{ rows, width: "100%" }} title={false} />
      </div>
    );
  }

  if (variant === "page") {
    return (
      <div
        className={className}
        role="status"
        aria-live="polite"
        aria-label={ariaLabel}
        style={{ display: "grid", gap: 16 }}
      >
        <Skeleton active paragraph={{ rows: 1, width: "40%" }} title={{ width: "20%" }} />
        <Skeleton.Button active block style={{ height: 80 }} />
        <Skeleton active paragraph={{ rows: 4 }} title={false} />
      </div>
    );
  }

  return (
    <div className={className} role="status" aria-live="polite" aria-label={ariaLabel}>
      <Skeleton active paragraph={{ rows }} />
    </div>
  );
}
