"use client";

import { Tag, Button } from "antd";
import { SwapOutlined } from "@ant-design/icons";
import { type GovernanceRun, getConfidence } from "../_lib/types";
import { ConfidenceTag } from "./ConfidenceTag";
import { SlaTimer } from "./SlaTimer";
import { formatTime, slaTier } from "@/lib/format-time";

interface ReviewCardProps {
  run: GovernanceRun;
  selected: boolean;
  onSelect: (checked: boolean) => void;
  onAdjudicate: () => void;
  onReassign: () => void;
}

export function ReviewCard({
  run,
  selected,
  onSelect,
  onAdjudicate,
  onReassign,
}: ReviewCardProps) {
  const conf = getConfidence(run);
  const slaDeadline = run.updated_at;
  const tier = slaTier(slaDeadline);

  const leftBarColor =
    tier === "overdue"
      ? "var(--danger-600)"
      : tier === "today"
        ? "var(--warning-600)"
        : "var(--line-strong)";

  const priorityLabel = tier === "overdue" ? "超时" : tier === "today" ? "今日" : null;
  const priorityColor = tier === "overdue" ? "error" : tier === "today" ? "warning" : "default";

  const reason =
    run.adoption_status === "pending_rule_guardrail"
      ? "规则冲突"
      : conf < 0.6
        ? "高敏风险"
        : "组织范围不明";
  const reasonColor =
    run.adoption_status === "pending_rule_guardrail"
      ? "warning"
      : conf < 0.6
        ? "error"
        : "warning";

  const { display: timeDisplay, iso: timeIso } = formatTime(run.updated_at);

  return (
    <div
      className="review-card grid grid-cols-[1fr_auto] gap-4 rounded-xl border border-[var(--line)] bg-[var(--surface)] px-5 py-4 cursor-pointer transition-shadow"
      style={{ borderLeft: `3px solid ${leftBarColor}` }}
      onClick={onAdjudicate}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onAdjudicate()}
      aria-label={`治理裁定：${run.normalized_ref_id}`}
    >
      {/* Left main content */}
      <div>
        <div className="flex items-center gap-2.5 mb-1">
          <input
            type="checkbox"
            checked={selected}
            aria-label={`选择 ${run.normalized_ref_id}`}
            onChange={(e) => onSelect(e.target.checked)}
            onClick={(e) => e.stopPropagation()}
          />
          <strong className="text-h3">{run.normalized_ref_id.slice(0, 24)}&hellip;</strong>
        </div>
        <div className="font-mono text-caption text-muted mb-2">
          {run.normalized_ref_id}
        </div>
        <div className="flex items-center gap-1.5 flex-wrap">
          {priorityLabel && (
            <Tag color={priorityColor} aria-label={`优先级：${priorityLabel}`}>
              {priorityLabel}
            </Tag>
          )}
          <Tag color={reasonColor}>{reason}</Tag>
          <ConfidenceTag confidence={conf} />
          <SlaTimer deadline={slaDeadline} />
        </div>
        <div className="mt-2 text-detail text-secondary">
          {run.adoption_status === "pending_rule_guardrail"
            ? "两条规则冲突需人工裁定。AI 建议与规则集均有命中，无法收敛。"
            : conf < 0.6
              ? "建议确认分级并指定受控 org_scope。AI 置信度不足触发规则护栏。"
              : "AI 建议组织范围置信度不足，规则窄化要求人工介入。"}
        </div>
        <div className="mt-1 text-caption text-muted">
          <time dateTime={timeIso} title={timeIso}>
            {timeDisplay}
          </time>
        </div>
      </div>

      {/* Right actions */}
      <div
        className="flex flex-col gap-2 items-end justify-center"
        onClick={(e) => e.stopPropagation()}
      >
        <Button type="primary" size="small" onClick={onAdjudicate}>
          裁定
        </Button>
        <Button size="small" icon={<SwapOutlined />} onClick={onReassign} aria-label="改派">
          改派
        </Button>
      </div>
    </div>
  );
}
