"use client";

/**
 * A1 四态规范 — Forbidden / MaskedCell
 *
 * 用于：
 *   1. 整页无权限（FullForbidden）
 *   2. 列表 / 详情中单字段无权限（MaskedCell，与权限矩阵 cant 单元格语义对齐）
 *
 * 视觉与 SPEC 一致：先鉴权再返回，L3/L4 默认脱敏；返回"内容受限"提示。
 */

import { Result, Button, Tooltip } from "antd";
import { LockOutlined } from "@ant-design/icons";
import type { ReactNode } from "react";

export interface ForbiddenProps {
  title?: string;
  description?: string;
  /** 用于回退的操作 */
  onBack?: () => void;
  extraActions?: ReactNode;
}

/** 整页无权限 */
export function Forbidden({
  title = "无访问权限",
  description = "你的角色或组织范围不包含该资源。如需访问，请联系平台管理员补齐授权。",
  onBack,
  extraActions,
}: ForbiddenProps) {
  return (
    <div role="alert">
      <Result
        status="403"
        title={title}
        subTitle={description}
        extra={
          <div style={{ display: "inline-flex", gap: 8 }}>
            {onBack ? (
              <Button type="primary" onClick={onBack}>
                返回上一页
              </Button>
            ) : null}
            {extraActions}
          </div>
        }
      />
    </div>
  );
}

export interface MaskedCellProps {
  /** hover 提示原因，如"L4 例外资产，需审批" */
  reason?: string;
  /** 行内显示文案，默认"内容受限" */
  label?: string;
}

/** 单字段脱敏占位，与 permissions heatmap "cant" 单元格保持视觉一致 */
export function MaskedCell({ reason, label = "内容受限" }: MaskedCellProps) {
  const node = (
    <span
      role="status"
      aria-label={reason ? `${label} — ${reason}` : label}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: 999,
        background: "var(--neutral-soft, #f3f4f6)",
        color: "var(--text-secondary)",
        fontSize: 12,
      }}
    >
      <LockOutlined style={{ fontSize: 11 }} aria-hidden="true" />
      {label}
    </span>
  );

  return reason ? <Tooltip title={reason}>{node}</Tooltip> : node;
}
