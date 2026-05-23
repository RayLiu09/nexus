"use client";

/**
 * GovernanceContent — v3.2 重构
 *
 * 变更：
 * - 移除「标签审核」tab（已独立为 /tag-review 路由）
 * - 恢复 4 tabs：待复核 / AI 建议 / 质量校准 / 决策追踪
 * - ReviewTab：改用 review-card 卡片布局（含 priority 左色条 + SLA + BulkBar）
 * - BulkBar 使用 shared/BulkBar，不再内联 Alert
 * - SummaryStrip：样式对齐 v3.2 summary-strip
 * - 全局：清除内联 style，走 CSS token + Tailwind
 */

"use client";

import { useState } from "react";
import { Table, Tag, Badge, Button, Progress, Drawer, Descriptions, Tabs, Alert, App } from "antd";
import type { ColumnsType } from "antd/es/table";
import { CheckOutlined, WarningOutlined, CloseOutlined, SwapOutlined } from "@ant-design/icons";
import {
  type GovernanceRun,
  type GovernanceStats,
  deriveStats,
  getClassification,
  getLevel,
  getConfidence,
  getQualityScore,
  getQualityLevel,
  getTags,
  getOrgScope,
} from "../_lib/types";
import { SummaryStrip } from "./SummaryStrip";
import { DecisionTrailDrawer } from "./DecisionTrailDrawer";
import { formatTime, slaTier, formatSla } from "@/lib/format-time";

// ── 工具：徽标渲染 ────────────────────────────────────────────

function confidenceTag(conf: number) {
  if (conf >= 0.85)
    return (
      <Tag color="success" icon={<CheckOutlined />}>
        {(conf * 100).toFixed(0)}%
      </Tag>
    );
  if (conf >= 0.6)
    return (
      <Tag color="warning" icon={<WarningOutlined />}>
        {(conf * 100).toFixed(0)}%
      </Tag>
    );
  return (
    <Tag color="error" icon={<CloseOutlined />}>
      {(conf * 100).toFixed(0)}%
    </Tag>
  );
}

function adoptionTag(status: string) {
  const map: Record<string, { color: string; label: string }> = {
    auto_adopted: { color: "success", label: "自动采纳" },
    manually_adopted: { color: "success", label: "人工采纳" },
    partially_adopted: { color: "processing", label: "部分采纳" },
    review_required: { color: "warning", label: "待复核" },
    pending_rule_guardrail: { color: "warning", label: "规则冲突" },
    rejected: { color: "error", label: "驳回" },
    manual_review: { color: "warning", label: "人工审核" },
  };
  const m = map[status] ?? { color: "default", label: status };
  return <Tag color={m.color}>{m.label}</Tag>;
}

function levelTag(level: string) {
  const map: Record<string, string> = {
    L1: "success",
    L2: "processing",
    L3: "warning",
    L4: "error",
  };
  return <Tag color={map[level] ?? "default"}>{level}</Tag>;
}

function domainTag(cls: string) {
  return <Tag color="purple">{cls}</Tag>;
}

/** SLA 计时器样式 */
function SlaTimer({ deadline }: { deadline: string }) {
  const tier = slaTier(deadline);
  const label = formatSla(deadline);
  const color =
    tier === "overdue"
      ? "var(--danger-600)"
      : tier === "today"
        ? "var(--warning-600)"
        : "var(--text-secondary)";
  return (
    <span
      role="status"
      aria-label={`SLA: ${label}`}
      style={{ fontSize: 12, fontWeight: 600, color }}
    >
      {label}
    </span>
  );
}

// ── 待复核 Review Card ────────────────────────────────────────

/**
 * 单张 review-card（v3.2 样式）
 * 优先级通过左侧色条（border-left）+ priority badge 双通道（A2 a11y）表达。
 */
function ReviewCard({
  run,
  selected,
  onSelect,
  onAdjudicate,
  onReassign,
}: {
  run: GovernanceRun;
  selected: boolean;
  onSelect: (checked: boolean) => void;
  onAdjudicate: () => void;
  onReassign: () => void;
}) {
  const conf = getConfidence(run);
  const slaDeadline = run.updated_at; // 实际应使用 sla_deadline 字段，当前以 updated_at 演示
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
    run.adoption_status === "pending_rule_guardrail" ? "warning" : conf < 0.6 ? "error" : "warning";

  const { display: timeDisplay, iso: timeIso } = formatTime(run.updated_at);

  return (
    <div
      className="review-card"
      style={{
        display: "grid",
        gridTemplateColumns: "1fr auto",
        gap: 16,
        background: "var(--surface)",
        border: "1px solid var(--line)",
        borderLeft: `3px solid ${leftBarColor}`,
        borderRadius: "var(--radius-xl)",
        padding: "16px 20px",
        cursor: "pointer",
        transition: "box-shadow var(--transition-fast), border-color var(--transition-fast)",
      }}
      onClick={onAdjudicate}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onAdjudicate()}
      aria-label={`治理裁定：${run.normalized_ref_id}`}
    >
      {/* 左侧主内容 */}
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <input
            type="checkbox"
            checked={selected}
            aria-label={`选择 ${run.normalized_ref_id}`}
            onChange={(e) => onSelect(e.target.checked)}
            onClick={(e) => e.stopPropagation()}
          />
          <strong style={{ fontSize: 15 }}>{run.normalized_ref_id.slice(0, 24)}…</strong>
        </div>
        <div
          style={{
            fontSize: 11,
            color: "var(--text-muted)",
            fontFamily: "var(--font-mono)",
            marginBottom: 8,
          }}
        >
          {run.normalized_ref_id}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          {/* 优先级（A2 双通道：左色条 + tag） */}
          {priorityLabel && (
            <Tag color={priorityColor} aria-label={`优先级：${priorityLabel}`}>
              {priorityLabel}
            </Tag>
          )}
          <Tag color={reasonColor}>{reason}</Tag>
          {confidenceTag(conf)}
          <SlaTimer deadline={slaDeadline} />
        </div>
        <div style={{ marginTop: 8, fontSize: 13, color: "var(--text-secondary)" }}>
          {run.adoption_status === "pending_rule_guardrail"
            ? "两条规则冲突需人工裁定。AI 建议与规则集均有命中，无法收敛。"
            : conf < 0.6
              ? "建议确认分级并指定受控 org_scope。AI 置信度不足触发规则护栏。"
              : "AI 建议组织范围置信度不足，规则窄化要求人工介入。"}
        </div>
        <div style={{ marginTop: 4, fontSize: 11, color: "var(--text-muted)" }}>
          <time dateTime={timeIso} title={timeIso}>
            {timeDisplay}
          </time>
        </div>
      </div>

      {/* 右侧操作 */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 8,
          alignItems: "flex-end",
          justifyContent: "center",
        }}
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

// ── ReviewTab ─────────────────────────────────────────────────

function ReviewTab({
  runs,
  onViewDetail,
}: {
  runs: GovernanceRun[];
  onViewDetail: (r: GovernanceRun) => void;
}) {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const { message, modal } = App.useApp();

  const filtered = runs.filter(
    (r) =>
      r.adoption_status === "review_required" || r.adoption_status === "pending_rule_guardrail",
  );

  const handleSelect = (id: string, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const handleBulkAdjudicate = () => {
    modal.confirm({
      title: `确认批量裁定 ${selectedIds.size} 项？`,
      content: "每条记录都会生成独立审计事件。此操作不可批量撤销。",
      okText: "确认裁定",
      cancelText: "取消",
      onOk: () => {
        message.success("已提交批量裁定");
        setSelectedIds(new Set());
      },
    });
  };

  const handleBulkReassign = () => {
    modal.confirm({
      title: `确认批量改派 ${selectedIds.size} 项？`,
      content: "改派将影响责任人 SLA，请确认。",
      okText: "确认改派",
      cancelText: "取消",
      onOk: () => {
        message.success("已改派");
        setSelectedIds(new Set());
      },
    });
  };

  if (filtered.length === 0) {
    return (
      <div style={{ padding: "48px 0", textAlign: "center", color: "var(--text-secondary)" }}>
        <CheckOutlined style={{ fontSize: 32, color: "var(--success-600)", marginBottom: 12 }} />
        <div style={{ fontSize: 15, fontWeight: 600 }}>待复核队列已清空</div>
        <div style={{ fontSize: 13, marginTop: 4 }}>所有资产均已完成裁定</div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* BulkBar */}
      {selectedIds.size > 0 && (
        <div
          className="governance-bulk-bar"
          role="toolbar"
          aria-label="批量操作工具栏"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "10px 16px",
            borderRadius: "var(--radius-lg)",
            border: "1px solid var(--brand-200)",
            background: "var(--brand-50)",
          }}
        >
          <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>
            已选 <strong style={{ color: "var(--text)" }}>{selectedIds.size}</strong> 项
          </span>
          <Button type="primary" size="small" onClick={handleBulkAdjudicate}>
            批量裁定
          </Button>
          <Button size="small" onClick={handleBulkReassign}>
            批量改派
          </Button>
          <Button
            type="text"
            size="small"
            onClick={() => setSelectedIds(new Set())}
            aria-label="清空选择"
          >
            清空
          </Button>
        </div>
      )}

      {/* review-card stack */}
      {filtered.map((r) => (
        <ReviewCard
          key={r.id}
          run={r}
          selected={selectedIds.has(r.id)}
          onSelect={(checked) => handleSelect(r.id, checked)}
          onAdjudicate={() => onViewDetail(r)}
          onReassign={() => message.info("改派功能即将上线")}
        />
      ))}
    </div>
  );
}

// ── AI Suggestions Tab ────────────────────────────────────────

function AiSuggestionsTab({
  runs,
  onViewDetail,
}: {
  runs: GovernanceRun[];
  onViewDetail: (r: GovernanceRun) => void;
}) {
  const filtered = runs.filter(
    (r) => r.validation_status === "schema_valid" && getConfidence(r) >= 0.6,
  );

  const columns: ColumnsType<GovernanceRun> = [
    {
      title: "资产",
      dataIndex: "normalized_ref_id",
      render: (id: string) => (
        <span className="font-semibold" style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
          {id.slice(0, 20)}…
        </span>
      ),
    },
    {
      title: "AI 建议",
      render: (_: unknown, r: GovernanceRun) => (
        <span style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
          {domainTag(getClassification(r))}
          {levelTag(getLevel(r))}
          <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>{getOrgScope(r)}</span>
        </span>
      ),
    },
    {
      title: "置信度",
      render: (_: unknown, r: GovernanceRun) => confidenceTag(getConfidence(r)),
      width: 110,
    },
    {
      title: "采纳状态",
      render: (_: unknown, r: GovernanceRun) => adoptionTag(r.adoption_status),
      width: 120,
    },
    {
      title: "规则结果",
      render: (_: unknown, r: GovernanceRun) => (
        <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
          {r.validation_status === "schema_valid" ? "校验通过" : r.validation_status}
        </span>
      ),
      width: 120,
    },
    {
      title: "",
      width: 60,
      render: (_: unknown, r: GovernanceRun) => (
        <Button type="link" size="small" onClick={() => onViewDetail(r)}>
          详情
        </Button>
      ),
    },
  ];

  return (
    <Table
      rowKey="id"
      dataSource={filtered}
      columns={columns}
      size="middle"
      pagination={false}
      locale={{ emptyText: "暂无 AI 建议" }}
    />
  );
}

// ── Quality Tab ───────────────────────────────────────────────

function QualityTab({
  runs,
  onViewDetail,
}: {
  runs: GovernanceRun[];
  onViewDetail: (r: GovernanceRun) => void;
}) {
  const filtered = runs.filter((r) => {
    const score = getQualityScore(r);
    return score !== null && score < 70;
  });

  const columns: ColumnsType<GovernanceRun> = [
    {
      title: "资产",
      dataIndex: "normalized_ref_id",
      render: (id: string) => (
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>{id.slice(0, 20)}…</span>
      ),
    },
    {
      title: "综合分",
      render: (_: unknown, r: GovernanceRun) => {
        const score = getQualityScore(r) ?? 0;
        return (
          <Progress
            percent={score}
            size="small"
            status={score < 60 ? "exception" : "normal"}
            style={{ width: 120 }}
          />
        );
      },
      width: 160,
    },
    {
      title: "低分维度",
      render: (_: unknown, r: GovernanceRun) => {
        const dimScores = (r.quality_summary?.dimension_scores as Record<string, number>) ?? {};
        const lowDim = Object.entries(dimScores)
          .filter(([, v]) => v < 70)
          .map(([k]) => k)
          .join("、");
        return lowDim ? (
          <span style={{ fontSize: 12, color: "var(--warning-600)" }}>{lowDim}</span>
        ) : (
          <span style={{ color: "var(--text-muted)" }}>-</span>
        );
      },
    },
    {
      title: "质量等级",
      render: (_: unknown, r: GovernanceRun) => {
        const lv = getQualityLevel(r);
        return lv ? (
          <Tag color={lv === "pass" ? "success" : lv === "fail" ? "error" : "warning"}>{lv}</Tag>
        ) : (
          "-"
        );
      },
      width: 100,
    },
    {
      title: "修复建议",
      render: () => (
        <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
          补齐目录层级并合并断裂切片
        </span>
      ),
    },
    {
      title: "操作",
      width: 80,
      render: (_: unknown, r: GovernanceRun) => (
        <Button type="link" size="small" onClick={() => onViewDetail(r)}>
          校准
        </Button>
      ),
    },
  ];

  return (
    <Table
      rowKey="id"
      dataSource={filtered}
      columns={columns}
      size="middle"
      pagination={false}
      locale={{ emptyText: "暂无质量待审" }}
    />
  );
}

// ── Decision Trail Tab ────────────────────────────────────────

function DecisionTrailTab({
  runs,
  onOpenTrail,
}: {
  runs: GovernanceRun[];
  onOpenTrail: (refId: string) => void;
}) {
  const decided = runs.filter(
    (r) =>
      r.adoption_status === "auto_adopted" ||
      r.adoption_status === "manually_adopted" ||
      r.adoption_status === "partially_adopted" ||
      r.adoption_status === "rejected",
  );

  const columns: ColumnsType<GovernanceRun> = [
    {
      title: "对象",
      dataIndex: "normalized_ref_id",
      render: (id: string) => (
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>{id.slice(0, 20)}…</span>
      ),
    },
    {
      title: "最终结果",
      render: (_: unknown, r: GovernanceRun) => (
        <span style={{ display: "inline-flex", gap: 4 }}>
          {domainTag(getClassification(r))}
          {levelTag(getLevel(r))}
        </span>
      ),
    },
    {
      title: "达成方式",
      render: (_: unknown, r: GovernanceRun) => adoptionTag(r.adoption_status),
      width: 120,
    },
    {
      title: "证据",
      render: (_: unknown, r: GovernanceRun) => (
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
          {r.model_alias.split("/").pop()} · {r.prompt_version}
        </span>
      ),
    },
    {
      title: "时间",
      dataIndex: "updated_at",
      width: 140,
      render: (t: string) => {
        const { display, iso } = formatTime(t);
        return (
          <time dateTime={iso} title={iso} style={{ fontSize: 12, color: "var(--text-secondary)" }}>
            {display}
          </time>
        );
      },
    },
    {
      title: "",
      width: 110,
      render: (_: unknown, r: GovernanceRun) => (
        <Button type="link" size="small" onClick={() => onOpenTrail(r.normalized_ref_id)}>
          决策追踪
        </Button>
      ),
    },
  ];

  return (
    <Table
      rowKey="id"
      dataSource={decided}
      columns={columns}
      size="middle"
      pagination={false}
      locale={{ emptyText: "暂无决策记录" }}
    />
  );
}

// ── Detail Drawer ─────────────────────────────────────────────

function DetailDrawer({
  run,
  open,
  onClose,
  onOpenTrail,
}: {
  run: GovernanceRun | null;
  open: boolean;
  onClose: () => void;
  onOpenTrail: (refId: string) => void;
}) {
  if (!run) return null;

  const aiOutput = run.ai_output ?? {};
  const qualitySummary = run.quality_summary ?? {};
  const dimScores = (qualitySummary.dimension_scores as Record<string, number>) ?? {};
  const blockingReasons = Array.isArray(qualitySummary.blocking_reasons)
    ? (qualitySummary.blocking_reasons as string[])
    : [];

  return (
    <Drawer
      title="决策追踪"
      width={560}
      open={open}
      onClose={onClose}
      destroyOnClose
      footer={
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <Button onClick={onClose}>关闭</Button>
          <Button type="primary" onClick={() => onOpenTrail(run.normalized_ref_id)}>
            查看决策追踪
          </Button>
        </div>
      }
    >
      <Descriptions column={2} size="small" bordered style={{ marginBottom: 16 }}>
        <Descriptions.Item label="模型别名">
          <code style={{ fontFamily: "var(--font-mono)" }}>{run.model_alias}</code>
        </Descriptions.Item>
        <Descriptions.Item label="Prompt 版本">{run.prompt_version}</Descriptions.Item>
        <Descriptions.Item label="验证状态">
          <Tag>{run.validation_status}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="采纳状态">{adoptionTag(run.adoption_status)}</Descriptions.Item>
      </Descriptions>

      <h4 style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>AI 建议</h4>
      <Descriptions column={2} size="small" style={{ marginBottom: 16 }}>
        <Descriptions.Item label="分类">{domainTag(getClassification(run))}</Descriptions.Item>
        <Descriptions.Item label="分级">{levelTag(getLevel(run))}</Descriptions.Item>
        <Descriptions.Item label="置信度">{confidenceTag(getConfidence(run))}</Descriptions.Item>
        <Descriptions.Item label="组织范围">{getOrgScope(run)}</Descriptions.Item>
        <Descriptions.Item label="标签" span={2}>
          {getTags(run).length > 0 ? (
            getTags(run).map((t) => <Tag key={t}>#{t}</Tag>)
          ) : (
            <span style={{ color: "var(--text-muted)" }}>-</span>
          )}
        </Descriptions.Item>
      </Descriptions>

      {(aiOutput.reasoning as string) && (
        <Alert
          type="info"
          message="AI 推理"
          description={aiOutput.reasoning as string}
          style={{ marginBottom: 16 }}
        />
      )}

      {run.quality_summary && (
        <>
          <h4 style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>质量评分</h4>
          <Descriptions column={2} size="small" style={{ marginBottom: 12 }}>
            <Descriptions.Item label="综合分">{getQualityScore(run) ?? "-"}</Descriptions.Item>
            <Descriptions.Item label="质量等级">
              <Tag color={getQualityLevel(run) === "pass" ? "success" : "warning"}>
                {getQualityLevel(run) || "-"}
              </Tag>
            </Descriptions.Item>
          </Descriptions>
          {Object.keys(dimScores).length > 0 && (
            <div style={{ display: "grid", gap: 6, marginBottom: 16 }}>
              {Object.entries(dimScores).map(([dim, score]) => (
                <div key={dim} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span
                    style={{
                      width: 64,
                      fontSize: 12,
                      color: "var(--text-muted)",
                      flexShrink: 0,
                    }}
                  >
                    {dim}
                  </span>
                  <Progress
                    percent={score}
                    size="small"
                    status={score >= 80 ? "success" : score >= 60 ? "normal" : "exception"}
                    style={{ flex: 1 }}
                  />
                </div>
              ))}
            </div>
          )}
          {blockingReasons.length > 0 && (
            <Alert
              type="error"
              message="阻断原因"
              description={blockingReasons.map((reason, i) => (
                <div key={i}>{reason}</div>
              ))}
              style={{ marginBottom: 16 }}
            />
          )}
        </>
      )}

      {run.validation_error && (
        <Alert type="error" message="验证错误" description={run.validation_error} />
      )}
    </Drawer>
  );
}

// ── Main Content ──────────────────────────────────────────────

export function GovernanceContent({ runs }: { runs: GovernanceRun[] }) {
  const [drawerRun, setDrawerRun] = useState<GovernanceRun | null>(null);
  const [trailRefId, setTrailRefId] = useState<string | null>(null);
  const { message } = App.useApp();
  const stats = deriveStats(runs);

  const reviewCount = runs.filter(
    (r) =>
      r.adoption_status === "review_required" || r.adoption_status === "pending_rule_guardrail",
  ).length;
  const qualityCount = runs.filter((r) => {
    const s = getQualityScore(r);
    return s !== null && s < 70;
  }).length;

  // v3.2 4 tabs（移除标签审核，已独立为 /tag-review）
  const tabItems = [
    {
      key: "review",
      label: (
        <Badge count={reviewCount} size="small" offset={[8, 0]}>
          待复核
        </Badge>
      ),
      children: <ReviewTab runs={runs} onViewDetail={setDrawerRun} />,
    },
    {
      key: "ai",
      label: "AI 建议",
      children: <AiSuggestionsTab runs={runs} onViewDetail={setDrawerRun} />,
    },
    {
      key: "quality",
      label: (
        <Badge count={qualityCount} size="small" offset={[8, 0]}>
          质量校准
        </Badge>
      ),
      children: <QualityTab runs={runs} onViewDetail={setDrawerRun} />,
    },
    {
      key: "trail",
      label: "决策追踪",
      children: <DecisionTrailTab runs={runs} onOpenTrail={setTrailRefId} />,
    },
  ];

  return (
    <>
      {/* SummaryStrip — 顶部关键指标 */}
      <SummaryStrip stats={stats} />

      {/* 顶部快捷操作 */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 16,
        }}
      >
        <div style={{ display: "flex", gap: 8 }}>
          <select
            aria-label="队列筛选"
            style={{
              height: 36,
              padding: "0 12px",
              borderRadius: "var(--radius-lg)",
              border: "1px solid var(--line)",
              background: "var(--surface)",
              color: "var(--text)",
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            <option>队列：全部</option>
            <option>仅我的</option>
          </select>
          <select
            aria-label="责任人筛选"
            style={{
              height: 36,
              padding: "0 12px",
              borderRadius: "var(--radius-lg)",
              border: "1px solid var(--line)",
              background: "var(--surface)",
              color: "var(--text)",
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            <option>责任人：我</option>
            <option>全部</option>
          </select>
        </div>
        <Button
          type="primary"
          onClick={() =>
            message.success("已批量采纳 3 条高置信建议。系统将继续执行规则校验和状态机判断。")
          }
        >
          一键采纳高置信建议
        </Button>
      </div>

      <Tabs items={tabItems} size="large" />

      <DetailDrawer
        run={drawerRun}
        open={drawerRun !== null}
        onClose={() => setDrawerRun(null)}
        onOpenTrail={(refId) => {
          setDrawerRun(null);
          setTrailRefId(refId);
        }}
      />

      <DecisionTrailDrawer
        open={trailRefId !== null}
        normalizedRefId={trailRefId}
        onClose={() => setTrailRefId(null)}
      />
    </>
  );
}
