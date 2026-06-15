"use client";

import Link from "next/link";
import { ReactNode } from "react";
import { Button, Empty } from "antd";
import { InboxOutlined } from "@ant-design/icons";

export interface EmptyStateAction {
  label: string;
  /** 提供 href 渲染为 Link；提供 onClick 渲染为按钮；优先 onClick */
  href?: string;
  onClick?: () => void;
  type?: "primary" | "default" | "text";
}

interface EmptyStateProps {
  /** 自定义图标，默认 InboxOutlined */
  icon?: ReactNode;
  /** 主标题 */
  title: ReactNode;
  /** 副标题/补充说明 */
  hint?: ReactNode;
  /** 0-3 个动作按钮（≤2 推荐） */
  actions?: EmptyStateAction[];
  /** 尺寸（影响纵向 padding 和图标大小）；默认 default */
  size?: "small" | "default" | "large";
  className?: string;
}

/**
 * 全局空状态组件 —— 替代散落的纯文本 "暂无数据" / "队列已清空"。
 *
 * 任何 0 数据的 Card / List 区域都应使用本组件，保持专业度和操作引导一致。
 */
export function EmptyState({
  icon,
  title,
  hint,
  actions = [],
  size = "default",
  className = "",
}: EmptyStateProps) {
  const padding = size === "small" ? "py-4" : size === "large" ? "py-12" : "py-8";
  const iconSize = size === "small" ? "text-3xl" : size === "large" ? "text-6xl" : "text-5xl";

  return (
    <div className={`flex flex-col items-center text-center ${padding} ${className}`}>
      <div className={`text-text-muted mb-3 opacity-50 ${iconSize}`} aria-hidden>
        {icon ?? <InboxOutlined />}
      </div>
      <div className="text-text mb-1 text-sm font-medium">{title}</div>
      {hint && <div className="text-text-muted mb-4 max-w-xs text-xs">{hint}</div>}
      {actions.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
          {actions.map((a, i) => {
            const btn = (
              <Button
                key={i}
                type={a.type ?? (i === 0 ? "primary" : "default")}
                size="small"
                onClick={a.onClick}
              >
                {a.label}
              </Button>
            );
            return a.href && !a.onClick ? (
              <Link key={i} href={a.href}>
                {btn}
              </Link>
            ) : (
              btn
            );
          })}
        </div>
      )}
    </div>
  );
}

/** 仅图标占位（无标题/无动作），用于极紧凑场景 */
export function EmptyMini({ text = "暂无数据" }: { text?: string }) {
  return (
    <div className="text-text-muted py-4 text-center text-xs">
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={text} />
    </div>
  );
}
