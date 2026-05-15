"use client";

import { useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/Badge";
import { EmptyState } from "@/components/EmptyState";

// -- v3.2 Prompt template type --
type PromptTemplate = {
  id: string;
  name: string;
  scenario: string;
  scenarioLabel: string;
  autoTrigger: string;
  pairedRuleSets: string[];
  modelAlias: string;
  redactionPolicy: string;
  version: string;
  status: "active" | "archived";
  lastModified: string;
  promptPreview: string;
  variables: string[];
};

const mockTemplates: PromptTemplate[] = [
  {
    id: "pt-1",
    name: "元数据治理",
    scenario: "metadata_governance",
    scenarioLabel: "AI 元数据治理",
    autoTrigger: "assetize → normalize 完成后触发 AI 治理",
    pairedRuleSets: ["数据域分类规则", "数据分级规则", "标签设置规则"],
    modelAlias: "LiteLLM/qwen-plus",
    redactionPolicy: "masked_content",
    version: "v3",
    status: "active",
    lastModified: "2h前",
    promptPreview:
      "你是一个企业数据资产治理专家。请根据以下标准化文档的元数据判断：\n1. 数据域(D1-D6)\n2. 分级(L1-L4)\n3. 推荐标签(7维度)\n4. 推荐组织范围",
    variables: ["title", "abstract", "source_hint", "content_snippet"]
  },
  {
    id: "pt-2",
    name: "质量评分",
    scenario: "quality_scoring",
    scenarioLabel: "AI 质量评分",
    autoTrigger: "AI 治理完成后自动触发质量评分",
    pairedRuleSets: ["AI 质量评分规则"],
    modelAlias: "LiteLLM/deepseek-v3",
    redactionPolicy: "metadata_only",
    version: "v2",
    status: "active",
    lastModified: "5d前",
    promptPreview:
      "你是一个文档质量评估专家。请评估以下标准化文档的质量：\n评估维度：完整性/结构性/可读性/安全性/可追溯性",
    variables: ["title", "abstract", "content_snippet", "parse_quality"]
  },
  {
    id: "pt-3",
    name: "敏感复核",
    scenario: "sensitive_review",
    scenarioLabel: "敏感内容识别",
    autoTrigger: "分级规则检测到高敏关键词时触发",
    pairedRuleSets: ["数据分级规则（高敏部分）"],
    modelAlias: "LiteLLM/qwen-plus",
    redactionPolicy: "full_content_private",
    version: "v1",
    status: "active",
    lastModified: "7d前",
    promptPreview:
      "你是一个内容安全审查专家。请判断以下文档片段是否包含敏感信息...",
    variables: ["title", "content_snippet"]
  }
];

function RedactionChip({ policy }: { policy: string }) {
  const labels: Record<string, string> = {
    masked_content: "内容脱敏",
    metadata_only: "仅元数据",
    full_content_private: "全内容私有 ⚠"
  };
  const tones: Record<string, "neutral" | "warning" | "danger"> = {
    masked_content: "neutral",
    metadata_only: "neutral",
    full_content_private: "danger"
  };
  return <span className={`tag ${tones[policy] === "danger" ? "tag-confidence-low" : ""}`}>{labels[policy] ?? policy}</span>;
}

export default function AiPromptsPage() {
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <>
      <PageHeader
        prototypeId="NX-13"
        title="AI Prompt 配置"
        description="系统内置 AI 治理 Prompt 模板，AI 治理环节自动选用对应模板+规则集组合。修改保存后立即生效，仅影响未来接入资产。"
        actions={
          <div className="flex gap-2">
            <button className="btn btn-secondary btn-sm">导入配置</button>
            <button className="btn btn-primary btn-sm">试验场 →</button>
          </div>
        }
      />

      {/* Auto-selection diagram */}
      <div className="notice notice-info">
        ⓘ <strong>自动选用机制：</strong>AI 治理触发 → 自动匹配 Prompt 模板 + 规则集组合。如果某类模板未配置，对应治理环节跳过（不阻塞流水线）。选用记录写入审计日志。
      </div>

      {/* Template cards */}
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
        {mockTemplates.map((tmpl) => {
          const isExpanded = expanded === tmpl.id;
          return (
            <div className="card" key={tmpl.id}>
              <div className="card-header">
                <div className="flex items-center gap-3">
                  <span className="card-title">{tmpl.name}</span>
                  <Badge label={tmpl.scenarioLabel} variant="brand" />
                  <Badge label={tmpl.version} variant="neutral" />
                  {tmpl.status === "active" && <Badge label="已生效" variant="success" />}
                </div>
                <span className="text-xs text-muted">最后修改: {tmpl.lastModified}</span>
              </div>

              <div className="card-body">
                {/* Config summary */}
                <div className="detail-grid">
                  <div>
                    <span>自动选用场景</span>
                    <strong className="text-sm">{tmpl.autoTrigger}</strong>
                  </div>
                  <div>
                    <span>配对规则集</span>
                    <strong className="text-sm">{tmpl.pairedRuleSets.join(", ")}</strong>
                  </div>
                  <div>
                    <span>LiteLLM 模型</span>
                    <strong className="text-sm mono-cell">{tmpl.modelAlias}</strong>
                  </div>
                  <div>
                    <span>脱敏策略</span>
                    <RedactionChip policy={tmpl.redactionPolicy} />
                  </div>
                </div>

                {/* Prompt preview */}
                {isExpanded && (
                  <div style={{ marginTop: "var(--space-4)" }}>
                    <div className="text-sm text-muted" style={{ marginBottom: "var(--space-2)" }}>Prompt 模板</div>
                    <div
                      style={{
                        background: "var(--gray-50)",
                        border: "1px solid var(--line)",
                        borderRadius: "var(--radius-md)",
                        padding: "var(--space-4)",
                        fontFamily: "var(--font-mono)",
                        fontSize: 12,
                        lineHeight: 1.6,
                        whiteSpace: "pre-wrap",
                        color: "var(--text-secondary)"
                      }}
                    >
                      {tmpl.promptPreview}
                    </div>
                    <div className="flex gap-2 flex-wrap" style={{ marginTop: "var(--space-2)" }}>
                      {tmpl.variables.map((v) => (
                        <span key={v} className="tag" style={{ background: "var(--brand-50)", color: "var(--brand-700)", fontFamily: "var(--font-mono)" }}>
                          {`{{${v}}}`}
                        </span>
                      ))}
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
                    {isExpanded ? "收起模板" : "查看模板"}
                  </button>
                  <button className="btn btn-ghost btn-sm">编辑模板</button>
                  <button className="btn btn-ghost btn-sm">复制为新版本</button>
                  <button className="btn btn-secondary btn-sm">在试验场打开 →</button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}
