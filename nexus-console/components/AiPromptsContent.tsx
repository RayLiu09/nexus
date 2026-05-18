"use client";

import { useState } from "react";
import { Badge } from "@/components/Badge";
import { EmptyState } from "@/components/EmptyState";
import { formatDateTime } from "@/lib/api";

type PromptProfile = {
  id: string;
  profile_name: string;
  profile_version: number;
  task_type: string;
  status: string;
  litellm_model_alias: string;
  prompt_version: string;
  output_schema_version: string;
  scoring_weight_version: string;
  temperature: number;
  max_input_tokens: number;
  redaction_policy: string;
  created_at: string;
  updated_at: string;
};

// Fallback mock data when API returns empty
const MOCK_FALLBACK: PromptProfile[] = [
  {
    id: "pp-1", profile_name: "元数据治理", profile_version: 3, task_type: "metadata_governance",
    status: "active", litellm_model_alias: "LiteLLM/qwen-plus", prompt_version: "v3",
    output_schema_version: "1.0", scoring_weight_version: "1.0", temperature: 0.3,
    max_input_tokens: 4096, redaction_policy: "masked_content",
    created_at: "2026-05-07T10:00:00Z", updated_at: "2026-05-14T08:23:00Z"
  },
  {
    id: "pp-2", profile_name: "质量评分", profile_version: 2, task_type: "quality_scoring",
    status: "active", litellm_model_alias: "LiteLLM/deepseek-v3", prompt_version: "v2",
    output_schema_version: "1.0", scoring_weight_version: "1.0", temperature: 0.2,
    max_input_tokens: 4096, redaction_policy: "metadata_only",
    created_at: "2026-05-01T10:00:00Z", updated_at: "2026-05-10T14:00:00Z"
  },
  {
    id: "pp-3", profile_name: "敏感复核", profile_version: 1, task_type: "sensitive_review",
    status: "active", litellm_model_alias: "LiteLLM/qwen-plus", prompt_version: "v1",
    output_schema_version: "1.0", scoring_weight_version: "1.0", temperature: 0.1,
    max_input_tokens: 2048, redaction_policy: "full_content_private",
    created_at: "2026-05-01T10:00:00Z", updated_at: "2026-05-08T11:00:00Z"
  }
];

function RedactionChip({ policy }: { policy: string }) {
  const labels: Record<string, string> = {
    masked_content: "内容脱敏",
    metadata_only: "仅元数据",
    full_content_private: "全内容私有 ⚠"
  };
  const isDanger = policy === "full_content_private";
  return (
    <span className={`tag ${isDanger ? "tag-confidence-low" : ""}`}>
      {labels[policy] ?? policy}
    </span>
  );
}

export function AiPromptsContent({ profiles }: { profiles: PromptProfile[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const data = profiles.length > 0 ? profiles : MOCK_FALLBACK;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
      {data.map((tmpl) => {
        const isExpanded = expanded === tmpl.id;
        return (
          <div className="card" key={tmpl.id}>
            <div className="card-header">
              <div className="flex items-center gap-3">
                <span className="card-title">{tmpl.profile_name}</span>
                <Badge label={tmpl.task_type} variant="brand" />
                <Badge label={`v${tmpl.profile_version}`} variant="neutral" />
                {tmpl.status === "active" && <Badge label="已生效" variant="success" />}
              </div>
              <span className="text-xs text-muted">{formatDateTime(tmpl.updated_at)}</span>
            </div>

            <div className="card-body">
              <div className="detail-grid">
                <div>
                  <span>任务类型</span>
                  <strong className="text-sm">{tmpl.task_type}</strong>
                </div>
                <div>
                  <span>LiteLLM 模型</span>
                  <strong className="text-sm mono-cell">{tmpl.litellm_model_alias}</strong>
                </div>
                <div>
                  <span>Prompt 版本</span>
                  <strong className="text-sm">{tmpl.prompt_version}</strong>
                </div>
                <div>
                  <span>脱敏策略</span>
                  <RedactionChip policy={tmpl.redaction_policy} />
                </div>
              </div>

              {isExpanded && (
                <div style={{ marginTop: "var(--space-4)" }}>
                  <div className="detail-grid">
                    <div>
                      <span>输出 Schema 版本</span>
                      <strong className="text-sm">{tmpl.output_schema_version}</strong>
                    </div>
                    <div>
                      <span>评分权重版本</span>
                      <strong className="text-sm">{tmpl.scoring_weight_version}</strong>
                    </div>
                    <div>
                      <span>Temperature</span>
                      <strong className="text-sm">{tmpl.temperature}</strong>
                    </div>
                    <div>
                      <span>Max Tokens</span>
                      <strong className="text-sm">{tmpl.max_input_tokens}</strong>
                    </div>
                  </div>
                </div>
              )}
            </div>

            <div className="card-footer">
              <div className="flex gap-2">
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => setExpanded(isExpanded ? null : tmpl.id)}
                >
                  {isExpanded ? "收起详情" : "查看详情"}
                </button>
                <button className="btn btn-ghost btn-sm">复制为新版本</button>
                <button className="btn btn-ghost btn-sm btn-danger">禁用</button>
              </div>
            </div>
          </div>
        );
      })}

      {data.length === 0 && (
        <EmptyState icon="✦" title="暂无 Prompt 配置" description="创建第一个 Prompt 配置以启用 AI 治理" />
      )}
    </div>
  );
}
