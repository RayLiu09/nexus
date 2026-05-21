"use client";

/**
 * A1 四态规范 — Empty
 *
 * 不只是"没数据"，而是给用户"接下来做什么"。
 * 必填：title + description；推荐：actions（主 CTA）。
 */

import { Empty as AntdEmpty } from "antd";
import type { ReactNode } from "react";

export interface EmptyProps {
  /** 主标题，用动词或事实陈述（如"还没有数据源"） */
  title: string;
  /** 副标题，给上下文（如"创建第一个数据源以开始接入"） */
  description?: string;
  /** 主 CTA + 次 CTA */
  actions?: ReactNode;
  /** 自定义图标；默认 Antd Empty 默认图 */
  image?: ReactNode;
  className?: string;
}

export function Empty({ title, description, actions, image, className }: EmptyProps) {
  return (
    <div
      className={className}
      role="status"
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "48px 24px",
        gap: 16,
        textAlign: "center",
      }}
    >
      <AntdEmpty
        image={image ?? AntdEmpty.PRESENTED_IMAGE_SIMPLE}
        description={
          <div style={{ display: "grid", gap: 4 }}>
            <strong style={{ color: "var(--text)", fontSize: 15 }}>{title}</strong>
            {description ? (
              <span style={{ color: "var(--text-secondary)", fontSize: 13 }}>{description}</span>
            ) : null}
          </div>
        }
      />
      {actions ? <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>{actions}</div> : null}
    </div>
  );
}
