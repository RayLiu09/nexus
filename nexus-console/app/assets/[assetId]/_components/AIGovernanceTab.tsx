"use client";

import { useState } from "react";
import { tagLabel, type TagDictionary } from "@/lib/tagLabels";
import { Card, Empty, Tag, Alert } from "antd";
import { StatusLabel } from "@/components/StatusLabel";
import { CopyableShortId } from "@/components/shared/CopyableShortId";
import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import {
  formatDateTime,
    type AIGovernanceRun,
} from "@/lib/api";
import { extractGovernanceTags } from "@/lib/governance-tags";

type Props = {
  runs: AIGovernanceRun[];
  tagDictionary?: TagDictionary;
};

const CLASSIFICATION_LABELS: Record<string, string> = {
  industry_policy: "产业政策",
  industry_report: "产业报告",
  sector_report: "行业报告",
  job_demand: "岗位需求数据",
  competency_analysis: "职业能力分析表",
  vocational_certificate: "职业类证书",
  teaching_standard: "专业教学标准",
  major_distribution: "专业布点数",
  talent_demand_report: "专业人才需求报告",
  talent_training_plan: "人才培养方案",
  major_profile: "专业简介",
};

function classificationLabel(output: Record<string, unknown>): string {
  const name = output.classification_name as string | undefined;
  if (name) return name;
  const code = (output.classification_code as string | undefined) ?? (output.classification as string | undefined);
  if (!code) return "";
  return CLASSIFICATION_LABELS[code] ?? code;
}

export function AIGovernanceTab({ runs, tagDictionary }: Props) {
  const [selected, setSelected] = useState<AIGovernanceRun | null>(null);

  if (runs.length === 0) {
    return (
      <Empty description="暂无 AI 治理记录 — 对该资产的标准化引用触发 AI 治理后，执行记录将显示在此处" />
    );
  }

  const run = selected ?? runs[0];
  const aiOutput = (run.ai_output ?? {}) as Record<string, unknown>;
  const evidenceRefs = Array.isArray(aiOutput.evidence_refs)
    ? (aiOutput.evidence_refs as Record<string, unknown>[])
    : [];
  const classification = classificationLabel(aiOutput);
  const tags = extractGovernanceTags(aiOutput);

  return (
    <div className="grid gap-4">
      {/* Run selector */}
      {runs.length > 1 && (
        <Card title="执行记录" styles={{ body: { padding: 0 } }}>
          {runs.map((r) => (
            <div
              key={r.id}
              className="grid grid-cols-[140px_120px_120px_1fr] items-center p-3 border-b border-[var(--line)] last:border-b-0 cursor-pointer hover:bg-[var(--brand-50)] transition-colors"
              style={{ background: r.id === run.id ? "var(--brand-50)" : undefined }}
              onClick={() => setSelected(r)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { setSelected(r); } }}
              role="button"
              tabIndex={0}
            >
              <CopyableShortId value={r.id} className="font-mono text-xs" />
              <span className="text-sm">{r.model_alias.split("/").pop()}</span>
              <StatusLabel value={r.validation_status} />
              <span className="text-xs text-muted">{formatDateTime(r.created_at)}</span>
            </div>
          ))}
        </Card>
      )}

      {/* Run detail */}
      <Card
        title="AI 建议"
        extra={
          <div className="flex gap-2">
            <Tag>{run.model_alias}</Tag>
            <Tag>{run.prompt_version}</Tag>
            <StatusLabel value={run.adoption_status} />
          </div>
        }
      >
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <div className="text-xs text-muted mb-1">分类建议</div>
            {classification
              ? <Tag>{classification}</Tag>
              : <span className="text-muted">-</span>}
          </div>
          <div>
            <div className="text-xs text-muted mb-1">分级建议</div>
            {(aiOutput.level as string) ? (
              <Tag color={["L3", "L4"].includes(aiOutput.level as string) ? "error" : "default"}>
                {aiOutput.level as string}
              </Tag>
            ) : <span className="text-muted">-</span>}
          </div>
          <div>
            <div className="text-xs text-muted mb-1">置信度</div>
            <ConfidenceBadge confidence={(aiOutput.confidence as number) ?? 0} />
          </div>
          <div>
            <div className="text-xs text-muted mb-1">标签建议</div>
            <div className="flex gap-1 flex-wrap">
              {tags.length > 0
                ? tags.map((t) => <Tag key={t}>{tagLabel(t, tagDictionary)}</Tag>)
                : <span className="text-muted text-sm">-</span>}
            </div>
          </div>
        </div>

        {(aiOutput.reasoning as string) && (
          <div className="mt-3 p-3 bg-[var(--gray-50)] rounded-lg text-detail text-muted leading-relaxed">
            {aiOutput.reasoning as string}
          </div>
        )}
      </Card>

      {/* Evidence refs */}
      {evidenceRefs.length > 0 && (
        <Card
          title="证据引用"
          extra={<Tag>{evidenceRefs.length} 条</Tag>}
          styles={{ body: { padding: 0 } }}
        >
          {evidenceRefs.map((ref, i) => (
            <div
              key={i}
              className="grid grid-cols-[120px_1fr_80px] items-center p-3 border-b border-[var(--line)] last:border-b-0"
            >
              <span className="text-sm text-muted">{String(ref.field)}</span>
              <span className="text-sm">{String(ref.value)}</span>
              <ConfidenceBadge confidence={(ref.confidence as number) ?? 0} />
            </div>
          ))}
        </Card>
      )}

      {run.validation_error && (
        <Alert type="error" title={`验证错误：${run.validation_error}`} showIcon />
      )}
    </div>
  );
}
