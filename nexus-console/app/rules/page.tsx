"use client";

import { useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/Badge";

// -- Rule set data shapes for v3.2 --
type RuleSetSummary = {
  id: string;
  name: string;
  ruleSetType: "domain_classification" | "data_classification" | "tag_labeling" | "quality_scoring";
  version: string;
  ruleCount: number;
  effectiveTime: string;
  lastModified: string;
};

const mockRuleSets: RuleSetSummary[] = [
  {
    id: "rs-1",
    name: "数据域分类规则",
    ruleSetType: "domain_classification",
    version: "v4",
    ruleCount: 12,
    effectiveTime: "2026-05-14 10:23",
    lastModified: "2h前"
  },
  {
    id: "rs-2",
    name: "数据分级规则",
    ruleSetType: "data_classification",
    version: "v2",
    ruleCount: 8,
    effectiveTime: "2026-05-11 14:00",
    lastModified: "3d前"
  },
  {
    id: "rs-3",
    name: "标签设置规则",
    ruleSetType: "tag_labeling",
    version: "v1",
    ruleCount: 15,
    effectiveTime: "2026-05-09 09:30",
    lastModified: "5d前"
  },
  {
    id: "rs-4",
    name: "AI 质量评分规则",
    ruleSetType: "quality_scoring",
    version: "v1",
    ruleCount: 6,
    effectiveTime: "2026-05-07 11:00",
    lastModified: "7d前"
  }
];

const ruleSetTypeLabels: Record<string, string> = {
  domain_classification: "数据域分类",
  data_classification: "数据分级",
  tag_labeling: "标签设置",
  quality_scoring: "AI 质量评分"
};

export default function RulesPage() {
  const [showUpload, setShowUpload] = useState<string | null>(null);

  return (
    <>
      <PageHeader
        prototypeId="NX-09"
        title="规则配置"
        description="规则后台存储在磁盘 JSON 文件中，具有固定结构。更新规则需：下载模板 → 本地编辑 → 上传校验 → 保存生效。仅影响未来接入资产。"
        actions={
          <div className="flex gap-2">
            <button className="btn btn-secondary btn-sm">📥 下载空模板</button>
            <button className="btn btn-primary btn-sm">+ 导入规则集</button>
          </div>
        }
      />

      {/* Info banner */}
      <div className="notice notice-info">
        ⓘ 规则变更保存后立即生效，仅对未来新接入的数据资产生效。已完成治理的历史资产不受影响。如需对历史资产重应用规则，请使用治理中心的批量重治理功能。
      </div>

      {/* Rule set cards */}
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
        {mockRuleSets.map((rs) => (
          <div className="card" key={rs.id}>
            <div className="card-header">
              <div className="flex items-center gap-3">
                <span className="card-title">{rs.name}</span>
                <Badge label={ruleSetTypeLabels[rs.ruleSetType] ?? rs.ruleSetType} variant="brand" />
                <Badge label={rs.version} variant="neutral" />
              </div>
              <span className="text-xs text-muted">最后修改: {rs.lastModified}</span>
            </div>

            <div className="card-body">
              {/* JSON preview */}
              <div
                style={{
                  background: "var(--gray-900)",
                  color: "#e5e7eb",
                  borderRadius: "var(--radius-md)",
                  padding: "var(--space-4)",
                  fontFamily: "var(--font-mono)",
                  fontSize: 12,
                  lineHeight: 1.5,
                  maxHeight: 160,
                  overflow: "hidden",
                  position: "relative"
                }}
              >
                <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
{`{
  "rule_set": "${rs.ruleSetType}",
  "version": "${rs.version}",
  "effective_time": "${rs.effectiveTime}",
  "rules": [ /* ${rs.ruleCount} rules */ ]
}`}
                </pre>
              </div>

              {/* Metadata row */}
              <div className="flex justify-between items-center" style={{ marginTop: "var(--space-3)" }}>
                <div className="flex gap-3 text-sm text-muted">
                  <span>规则数: <strong>{rs.ruleCount}</strong></span>
                  <span>生效时间: {rs.effectiveTime}</span>
                </div>
              </div>
            </div>

            <div className="card-footer">
              <div className="flex gap-2">
                <button className="btn btn-secondary btn-sm">📥 下载模板</button>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => setShowUpload(showUpload === rs.id ? null : rs.id)}
                >
                  📤 上传更新
                </button>
                <button className="btn btn-ghost btn-sm">在线编辑</button>
                <button className="btn btn-ghost btn-sm">校验语法</button>
              </div>

              {/* Upload panel */}
              {showUpload === rs.id && (
                <div
                  style={{
                    marginTop: "var(--space-4)",
                    padding: "var(--space-5)",
                    border: "2px dashed var(--brand-300)",
                    borderRadius: "var(--radius-lg)",
                    background: "var(--brand-50)",
                    textAlign: "center"
                  }}
                >
                  <p className="text-sm text-muted" style={{ marginBottom: "var(--space-3)" }}>
                    Step 2: 上传编辑后的 JSON 文件
                  </p>
                  <div
                    style={{
                      padding: "var(--space-6)",
                      border: "2px dashed var(--line-strong)",
                      borderRadius: "var(--radius-md)",
                      background: "var(--surface)",
                      cursor: "pointer"
                    }}
                  >
                    <span style={{ fontSize: 24 }}>📄</span>
                    <p className="text-sm text-muted">拖拽文件到此处或 <span className="text-link">选择文件</span></p>
                    <p className="text-xs text-muted">支持: .json · 最大: 500KB</p>
                  </div>
                  <div className="flex justify-center gap-2" style={{ marginTop: "var(--space-3)" }}>
                    <button className="btn btn-ghost btn-sm" onClick={() => setShowUpload(null)}>取消</button>
                    <button className="btn btn-primary btn-sm">保存并生效</button>
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
