"use client";

/**
 * DecisionTrailDrawer — 按 normalized_ref_id 拉取 GovernanceResult 并按角色脱敏展示 decision_trail。
 *
 * 视图角色与后端对齐：
 * - full / operator / public（见 decisionTrail.types.ts）。
 * 切换 view 时重新请求，避免在前端"再次脱敏"造成与后端契约不一致。
 */

import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Descriptions,
  Drawer,
  Empty,
  Segmented,
  Skeleton,
  Space,
  Tag,
  Timeline,
  Typography,
} from "antd";
import {
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  CloseCircleOutlined,
} from "@ant-design/icons";
import type {
  AdoptionStatus,
  DecisionField,
  DecisionTrailEntry,
  DecisionTrailView,
  GovernanceResultRead,
} from "../_lib/decisionTrail.types";
import { fetchGovernanceResultForRef } from "../_lib/governanceResultApi";
import { tagLabel, type TagDictionary } from "@/lib/tagLabels";

const CLASS_LABELS: Record<string, string> = {
  industry_policy: "产业政策",
  industry_report: "产业报告",
  sector_report: "行业报告",
  job_demand: "岗位需求数据",
  competency_analysis: "职业能力分析表",
  vocational_certificate: "职业类证书",
  teaching_standard: "专业教学标准",
  program_distribution: "专业布点数",
  talent_demand_report: "专业人才需求报告",
  talent_training_plan: "人才培养方案",
  program_profile: "专业简介",
};

function classLabel(code: string | null | undefined): string {
  if (!code) return "-";
  return CLASS_LABELS[code] ?? code;
}

const VIEW_OPTIONS: { label: string; value: DecisionTrailView }[] = [
  { label: "完整视图", value: "full" },
  { label: "运维视图", value: "operator" },
  { label: "对外视图", value: "public" },
];

const FIELD_LABELS: Record<DecisionField, string> = {
  classification: "数据分类",
  level: "数据分级",
  tags: "数据标签",
  quality: "质量评分",
};

const ADOPTION_META: Record<
  AdoptionStatus,
  { color: string; label: string; icon: React.ReactNode }
> = {
  auto_adopted: { color: "success", label: "自动采纳", icon: <CheckCircleOutlined /> },
  review_required: { color: "warning", label: "待复核", icon: <ExclamationCircleOutlined /> },
  rejected: { color: "error", label: "驳回", icon: <CloseCircleOutlined /> },
};

const REDACTED_TOKEN = "***redacted***";

interface DecisionTrailDrawerProps {
  open: boolean;
  normalizedRefId: string | null;
  onClose: () => void;
  tagDictionary: TagDictionary;
  /** Fallback tags from the AI governance run's ai_output — used when
   *  result.tags is empty (e.g. governance result hasn't been persisted). */
  fallbackTags?: unknown;
}

export function DecisionTrailDrawer({ open, normalizedRefId, onClose, tagDictionary, fallbackTags }: DecisionTrailDrawerProps) {
  const [view, setView] = useState<DecisionTrailView>("full");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<GovernanceResultRead | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (refId: string, v: DecisionTrailView) => {
    setLoading(true);
    setError(null);
    const r = await fetchGovernanceResultForRef(refId, v);
    if (r.ok) {
      setResult(r.data);
    } else {
      setResult(null);
      // 404（尚未生成裁定）当作空状态而非错误
      if (r.error && !/404|not found/i.test(r.error)) {
        setError(r.error);
      }
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    if (open && normalizedRefId) {
      load(normalizedRefId, view);
    }
  }, [open, normalizedRefId, view, load]);

  // 关闭时重置视图，避免下次打开沿用上次切换（在事件处理器中触发，避免 effect 引发级联渲染）
  const handleClose = useCallback(() => {
    setView("full");
    onClose();
  }, [onClose]);

  return (
    <Drawer
      title="决策追踪"
      size={640}
      open={open}
      onClose={handleClose}
      destroyOnClose
      extra={
        <Segmented<DecisionTrailView>
          size="small"
          options={VIEW_OPTIONS}
          value={view}
          onChange={(v) => setView(v)}
          aria-label="决策追踪视图切换"
        />
      }
    >
      <DrawerBody loading={loading} error={error} view={view} result={result} tagDictionary={tagDictionary} fallbackTags={fallbackTags} />
    </Drawer>
  );
}

interface DrawerBodyProps {
  loading: boolean;
  error: string | null;
  view: DecisionTrailView;
  result: GovernanceResultRead | null;
  tagDictionary: TagDictionary;
  fallbackTags?: unknown;
}

function DrawerBody({ loading, error, view, result, tagDictionary, fallbackTags }: DrawerBodyProps) {
  if (loading) {
    return <Skeleton active paragraph={{ rows: 6 }} />;
  }

  if (error) {
    return <Alert type="error" showIcon title="无法加载决策追踪" description={error} />;
  }

  if (!result) {
    return (
      <Empty description="尚未生成治理裁定（normalized_ref 还未走完 governance_decision 阶段）" />
    );
  }

  // Merge tags: prefer committed result tags, fall back to AI run output tags
  const resolvedTags: string[] = (() => {
    if (result.tags.length > 0) return result.tags;
    if (Array.isArray(fallbackTags)) return fallbackTags.filter((t): t is string => typeof t === "string");
    return [];
  })();

  const trail = result.decision_trail ?? [];

  return (
    <Space orientation="vertical" size="large" className="w-full">
      <OutcomeSummary result={{ ...result, tags: resolvedTags }} tagDictionary={tagDictionary} />

      {view === "public" ? (
        <Alert
          type="info"
          showIcon
          message="对外视图：仅暴露最终裁定结果，不包含 AI 建议与置信度等内部证据。"
        />
      ) : trail.length === 0 ? (
        <Empty description="无字段级裁定记录" />
      ) : (
        <Timeline
          items={trail.map((entry, i) => ({
            key: `${entry.field_name}-${i}`,
            color: ADOPTION_META[entry.adoption_status]?.color ?? "blue",
            content: <TrailItem entry={entry} view={view} tagDictionary={tagDictionary} />,
          }))}
        />
      )}
    </Space>
  );
}

function OutcomeSummary({ result, tagDictionary }: { result: GovernanceResultRead; tagDictionary: TagDictionary }) {
  return (
    <Descriptions size="small" bordered column={2}>
      <Descriptions.Item label="数据分类">
        {result.classification ? <Tag color="purple">{classLabel(result.classification)}</Tag> : "-"}
      </Descriptions.Item>
      <Descriptions.Item label="数据分级">
        {result.level ? <Tag>{result.level}</Tag> : "-"}
      </Descriptions.Item>
      <Descriptions.Item label="标签" span={2}>
        {result.tags?.length ? (
          <Space size={4} wrap>
            {result.tags.map((t) => (
              <Tag key={t}>#{tagLabel(t, tagDictionary)}</Tag>
            ))}
          </Space>
        ) : (
          "-"
        )}
      </Descriptions.Item>
      <Descriptions.Item label="组织范围">{result.org_scope ?? "-"}</Descriptions.Item>
      <Descriptions.Item label="索引准入">
        <Tag color={result.index_admission ? "success" : "default"}>
          {result.index_admission ? "已准入" : "未准入"}
        </Tag>
      </Descriptions.Item>
      <Descriptions.Item label="状态">{result.status}</Descriptions.Item>
      <Descriptions.Item label="规则版本">
        <Typography.Text className="font-mono text-xs">
          {result.rules_schema_version ?? "-"}
        </Typography.Text>
      </Descriptions.Item>
    </Descriptions>
  );
}

function TrailItem({ entry, view, tagDictionary }: { entry: DecisionTrailEntry; view: DecisionTrailView; tagDictionary: TagDictionary }) {
  const meta = ADOPTION_META[entry.adoption_status];
  const showSuggestion = view === "full" || view === "operator";
  const showConfidence = view === "full";

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <strong className="text-[13px]">{FIELD_LABELS[entry.field_name]}</strong>
        <Tag color={meta?.color} icon={meta?.icon}>
          {meta?.label ?? entry.adoption_status}
        </Tag>
        {showConfidence && typeof entry.ai_confidence === "number" && (
          <span className="text-xs text-[var(--text-muted)]">
            置信度 {(entry.ai_confidence * 100).toFixed(0)}%
          </span>
        )}
      </div>

      <div className="text-[13px]">
        最终值：
        <ValueChip value={entry.final_value} fieldName={entry.field_name} tagDictionary={tagDictionary} />
      </div>

      {showSuggestion && entry.ai_suggestion !== undefined && (
        <div className="text-[13px] text-[var(--text-secondary)]">
          AI 建议：
          {entry.ai_suggestion === REDACTED_TOKEN ? (
            <Tag color="default">{REDACTED_TOKEN}</Tag>
          ) : (
            <ValueChip value={entry.ai_suggestion} fieldName={entry.field_name} tagDictionary={tagDictionary} />
          )}
        </div>
      )}

      {entry.review_reason && (
        <Alert type="warning" showIcon title={entry.review_reason} className="mt-1" />
      )}

      <ThresholdView check={entry.threshold_check} />
    </div>
  );
}

function ValueChip({ value, fieldName, tagDictionary }: { value: unknown; fieldName?: DecisionField; tagDictionary: TagDictionary }) {
  if (value === null || value === undefined) return <span className="text-muted">-</span>;
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-muted">-</span>;
    return (
      <Space size={4} wrap>
        {(value as unknown[]).map((v, i) => (
          <Tag key={`${String(v)}-${i}`}>{fieldName === "tags" ? tagLabel(String(v), tagDictionary) : String(v)}</Tag>
        ))}
      </Space>
    );
  }
  if (typeof value === "object") {
    return (
      <Typography.Text className="font-mono text-xs">
        {JSON.stringify(value)}
      </Typography.Text>
    );
  }
  return <Tag color="blue">{fieldName === "tags" ? tagLabel(String(value), tagDictionary) : String(value)}</Tag>;
}

function ThresholdView({ check }: { check: Record<string, unknown> }) {
  const entries = Object.entries(check ?? {});
  if (entries.length === 0) return null;
  return (
    <details className="mt-1 text-xs text-[var(--text-muted)]">
      <summary className="cursor-pointer select-none">阈值检查详情</summary>
      <ul className="mt-1 ml-4 list-disc">
        {entries.map(([k, v]) => (
          <li key={k}>
            <span className="font-mono">{k}</span>：
            <span className="font-mono">{formatValue(v)}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return "-";
  if (Array.isArray(v) || typeof v === "object") return JSON.stringify(v);
  return String(v);
}
