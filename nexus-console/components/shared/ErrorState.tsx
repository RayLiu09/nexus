"use client";

/**
 * A1 四态规范 — ErrorState
 *
 * 错误信息四要素（A4 微文案模板）：
 *   1. What  — title 简短描述
 *   2. Why   — description 给上下文 / 错误原因
 *   3. Next  — actions 重试 / 联系支持 / 跳转
 *   4. Trace — traceId 末 8 位可显示，全文 hover 复制
 */

import { Button, Result, Tooltip, App as AntdApp } from "antd";
import { ReloadOutlined, CopyOutlined } from "@ant-design/icons";
import type { ReactNode } from "react";

export interface ErrorStateProps {
  /** 简短标题，回答"发生了什么" */
  title: string;
  /** 详细描述，回答"为什么 / 怎么办" */
  description?: string;
  /** trace_id，便于售后定位 */
  traceId?: string;
  /** 重试回调；提供则显示重试按钮 */
  onRetry?: () => void;
  /** 额外操作（如"联系支持"、"返回首页"） */
  extraActions?: ReactNode;
  /** Antd Result status，默认 error */
  status?: "error" | "warning" | "403" | "404" | "500";
  className?: string;
}

function shortTrace(t: string): string {
  if (t.length <= 12) return t;
  return `…${t.slice(-8)}`;
}

export function ErrorState({
  title,
  description,
  traceId,
  onRetry,
  extraActions,
  status = "error",
  className,
}: ErrorStateProps) {
  const { message } = AntdApp.useApp();

  const handleCopy = async () => {
    if (!traceId) return;
    try {
      await navigator.clipboard.writeText(traceId);
      message.success("trace_id 已复制");
    } catch {
      message.error("复制失败，请手动选择文本");
    }
  };

  const subTitle = (
    <div style={{ display: "grid", gap: 8 }}>
      {description ? <div>{description}</div> : null}
      {traceId ? (
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            color: "var(--text-secondary)",
            fontSize: 12,
            justifyContent: "center",
          }}
        >
          <span>trace_id:</span>
          <Tooltip title={traceId}>
            <code style={{ fontFamily: "var(--font-mono)" }}>{shortTrace(traceId)}</code>
          </Tooltip>
          <Button
            size="small"
            type="text"
            icon={<CopyOutlined />}
            onClick={handleCopy}
            aria-label="复制 trace_id"
          />
        </div>
      ) : null}
    </div>
  );

  return (
    <div className={className} role="alert">
      <Result
        status={status}
        title={title}
        subTitle={subTitle}
        extra={
          <div style={{ display: "inline-flex", gap: 8, flexWrap: "wrap" }}>
            {onRetry ? (
              <Button type="primary" icon={<ReloadOutlined />} onClick={onRetry}>
                重试
              </Button>
            ) : null}
            {extraActions}
          </div>
        }
      />
    </div>
  );
}
