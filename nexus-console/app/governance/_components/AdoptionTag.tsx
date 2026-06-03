"use client";

import { Tag } from "antd";

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  auto_adopted: { color: "success", label: "自动采纳" },
  manually_adopted: { color: "success", label: "人工采纳" },
  partially_adopted: { color: "processing", label: "部分采纳" },
  review_required: { color: "warning", label: "待复核" },
  pending_rule_guardrail: { color: "warning", label: "规则冲突" },
  rejected: { color: "error", label: "驳回" },
  manual_review: { color: "warning", label: "人工审核" },
};

export function AdoptionTag({ status }: { status: string }) {
  const m = STATUS_MAP[status] ?? { color: "default", label: status };
  return <Tag color={m.color}>{m.label}</Tag>;
}
