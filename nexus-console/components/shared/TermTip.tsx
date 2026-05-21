"use client";

/**
 * A4 微文案 — TermTip
 *
 * 业务术语 hover 解释。首次出现处包裹术语，鼠标移上时显示定义。
 *
 * 用法：
 *   <TermTip term="normalize">标准化</TermTip>
 *   <TermTip term="org_scope">组织范围</TermTip>
 *
 * 词库放在 lib/glossary.ts；未命中的 term 仍渲染 children，但无 tooltip。
 */

import { Tooltip } from "antd";
import { glossary } from "@/lib/glossary";

export interface TermTipProps {
  term: string;
  children: React.ReactNode;
}

export function TermTip({ term, children }: TermTipProps) {
  const def = glossary[term];

  if (!def) return <>{children}</>;

  return (
    <Tooltip title={def} placement="top">
      <span
        style={{
          borderBottom: "1px dashed var(--text-muted)",
          cursor: "help",
        }}
      >
        {children}
      </span>
    </Tooltip>
  );
}
