"use client";

/**
 * A6 徽标语义优先级矩阵 — BadgeRow
 *
 * 一行徽标硬上限 budget=3，超出按 priority 折叠到 "+N 更多"。
 * 优先级（高 → 低）：status → priority → level → domain → confidence → sla → type → audit
 */

import { Popover } from "antd";
import type { ReactNode } from "react";

export type BadgeKind =
  | "status"
  | "priority"
  | "level"
  | "domain"
  | "confidence"
  | "sla"
  | "type"
  | "audit";

const PRIORITY_ORDER: BadgeKind[] = [
  "status",
  "priority",
  "level",
  "domain",
  "confidence",
  "sla",
  "type",
  "audit",
];

const RANK: Record<BadgeKind, number> = PRIORITY_ORDER.reduce(
  (acc, k, i) => {
    acc[k] = i;
    return acc;
  },
  {} as Record<BadgeKind, number>,
);

export interface BadgeItem {
  kind: BadgeKind;
  /** 直接渲染的节点（chip / tag / status-dot） */
  node: ReactNode;
  /** 折叠时 Popover 列表中的可读文案 */
  label: string;
  /** 用作 React key */
  key: string;
}

export interface BadgeRowProps {
  badges: BadgeItem[];
  budget?: number;
  className?: string;
}

export function BadgeRow({ badges, budget = 3, className }: BadgeRowProps) {
  const sorted = [...badges].sort((a, b) => RANK[a.kind] - RANK[b.kind]);
  const visible = sorted.slice(0, budget);
  const overflow = sorted.slice(budget);

  return (
    <div
      className={className}
      style={{ display: "inline-flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}
    >
      {visible.map((b) => (
        <span key={b.key}>{b.node}</span>
      ))}
      {overflow.length > 0 ? (
        <Popover
          title="更多标签"
          content={
            <div style={{ display: "grid", gap: 6, minWidth: 180 }}>
              {overflow.map((b) => (
                <div
                  key={b.key}
                  style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}
                >
                  {b.node}
                  <span style={{ color: "var(--text-secondary)" }}>{b.label}</span>
                </div>
              ))}
            </div>
          }
        >
          <span
            role="button"
            tabIndex={0}
            aria-label={`查看其余 ${overflow.length} 个标签`}
            style={{
              display: "inline-flex",
              alignItems: "center",
              padding: "2px 8px",
              borderRadius: 999,
              background: "var(--surface-alt)",
              border: "1px solid var(--line)",
              color: "var(--text-secondary)",
              fontSize: 12,
              cursor: "pointer",
            }}
          >
            +{overflow.length} 更多
          </span>
        </Popover>
      ) : null}
    </div>
  );
}
