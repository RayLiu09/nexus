"use client";

import { useState } from "react";
import { Tabs } from "@/components/Tabs";
import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { StatusLabel } from "@/components/StatusLabel";
import { ProgressBar } from "@/components/ProgressBar";
import { Badge } from "@/components/Badge";
import { apiBaseUrl } from "@/lib/api";

type AIGovernanceRun = {
  id: string;
  normalized_ref_id: string;
  profile_id: string;
  model_alias: string;
  prompt_version: string;
  ai_output: Record<string, unknown> | null;
  quality_summary: Record<string, unknown> | null;
  validation_status: string;
  adoption_status: string;
  validation_error: string | null;
  created_at: string;
  updated_at: string;
};

type DrawerRun = AIGovernanceRun & { _label: string };

const queueTabs = [
  { id: "review", label: "待复核", badgeTone: "danger" as const },
  { id: "quality", label: "质量待审", badgeTone: "warning" as const },
  { id: "ai-suggest", label: "AI 建议" },
  { id: "all", label: "全部" },
];

function getClassification(run: AIGovernanceRun): string {
  return (run.ai_output?.classification as string) ?? "-";
}
function getLevel(run: AIGovernanceRun): string {
  return (run.ai_output?.level as string) ?? "-";
}
function getConfidence(run: AIGovernanceRun): number {
  return (run.ai_output?.confidence as number) ?? 0;
}
function getQualityScore(run: AIGovernanceRun): number | null {
  const qs = run.quality_summary;
  if (!qs) return null;
  return (qs.quality_score as number) ?? null;
}
function getQualityLevel(run: AIGovernanceRun): string {
  return (run.quality_summary?.quality_level as string) ?? "";
}
function getTags(run: AIGovernanceRun): string[] {
  const t = run.ai_output?.tags;
  return Array.isArray(t) ? (t as string[]) : [];
}
function getLabel(run: AIGovernanceRun): string {
  const cls = getClassification(run);
  const lv = getLevel(run);
  const alias = run.model_alias.split("/").pop() ?? run.model_alias;
  return `${cls !== "-" ? cls : "?"} · ${lv !== "-" ? lv : "?"} · ${alias} ${run.prompt_version}`;
}

function filterRuns(runs: AIGovernanceRun[], tab: string): AIGovernanceRun[] {
  switch (tab) {
    case "review":
      return runs.filter(
        (r) => r.adoption_status === "review_required" || r.adoption_status === "pending_rule_guardrail"
      );
    case "quality": {
      return runs.filter((r) => {
        const score = getQualityScore(r);
        return score !== null && score < 70;
      });
    }
    case "ai-suggest":
      return runs.filter(
        (r) => r.validation_status === "schema_valid" && getConfidence(r) >= 0.6
      );
    default:
      return runs;
  }
}

function DecisionDrawer({ run, onClose }: { run: DrawerRun; onClose: () => void }) {
  const aiOutput = run.ai_output ?? {};
  const qualitySummary = run.quality_summary ?? {};
  const evidenceRefs = Array.isArray(aiOutput.evidence_refs)
    ? (aiOutput.evidence_refs as Record<string, unknown>[])
    : [];
  const checkItems = Array.isArray(qualitySummary.check_items)
    ? (qualitySummary.check_items as Record<string, unknown>[])
    : [];
  const blockingReasons = Array.isArray(qualitySummary.blocking_reasons)
    ? (qualitySummary.blocking_reasons as string[])
    : [];
  const dimScores = (qualitySummary.dimension_scores as Record<string, number>) ?? {};

  return (
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 50,
        display: "flex", justifyContent: "flex-end",
      }}
    >
      <div
        style={{ flex: 1, background: "rgba(0,0,0,0.3)" }}
        onClick={onClose}
      />
      <div
        style={{
          width: 520, background: "var(--surface)", overflowY: "auto",
          padding: "var(--space-6)", boxShadow: "-4px 0 24px rgba(0,0,0,0.12)",
          display: "flex", flexDirection: "column", gap: "var(--space-5)",
        }}
      >
        <div className="flex justify-between items-center">
          <strong style={{ fontSize: 16 }}>决策追踪</strong>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>✕</button>
        </div>

        {/* Run meta */}
        <div className="card" style={{ background: "var(--gray-50)" }}>
          <div className="card-body">
            <div className="detail-grid">
              <div><span>模型别名</span><strong className="mono-cell text-sm">{run.model_alias}</strong></div>
              <div><span>Prompt 版本</span><strong className="text-sm">{run.prompt_version}</strong></div>
              <div><span>验证状态</span><StatusLabel value={run.validation_status} /></div>
              <div><span>采纳状态</span><StatusLabel value={run.adoption_status} /></div>
            </div>
          </div>
        </div>

        {/* AI suggestions */}
        <div>
          <div className="section-label" style={{ marginBottom: "var(--space-2)" }}>AI 建议</div>
          <div className="detail-grid">
            <div>
              <span>分类</span>
              <Badge label={getClassification(run)} variant="brand" />
            </div>
            <div>
              <span>分级</span>
              <Badge
                label={getLevel(run)}
                variant={["L3", "L4"].includes(getLevel(run)) ? "danger" : "neutral"}
              />
            </div>
            <div>
              <span>置信度</span>
              <ConfidenceBadge confidence={getConfidence(run)} />
            </div>
            <div>
              <span>标签</span>
              <div className="flex gap-1 flex-wrap">
                {getTags(run).length > 0
                  ? getTags(run).map((t) => <span key={t} className="tag">{t}</span>)
                  : <span className="text-muted text-sm">-</span>}
              </div>
            </div>
          </div>
          {(aiOutput.reasoning as string) && (
            <div
              style={{
                marginTop: "var(--space-3)", padding: "var(--space-3)",
                background: "var(--gray-50)", borderRadius: "var(--radius-md)",
                fontSize: 13, color: "var(--text-muted)", lineHeight: 1.6,
              }}
            >
              {aiOutput.reasoning as string}
            </div>
          )}
        </div>

        {/* Evidence refs */}
        {evidenceRefs.length > 0 && (
          <div>
            <div className="section-label" style={{ marginBottom: "var(--space-2)" }}>证据引用</div>
            <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
              {evidenceRefs.map((ref, i) => (
                <div
                  key={i}
                  style={{
                    padding: "var(--space-2) var(--space-3)",
                    background: "var(--gray-50)", borderRadius: "var(--radius-sm)",
                    fontSize: 13,
                  }}
                >
                  <span className="text-muted">{String(ref.field)}</span>
                  {" → "}
                  <span>{String(ref.value)}</span>
                  <span className="text-muted" style={{ marginLeft: 8 }}>
                    置信度 {((ref.confidence as number) * 100).toFixed(0)}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Quality summary */}
        {run.quality_summary && (
          <div>
            <div className="section-label" style={{ marginBottom: "var(--space-2)" }}>质量评分</div>
            <div className="detail-grid" style={{ marginBottom: "var(--space-3)" }}>
              <div>
                <span>综合分</span>
                <strong>{getQualityScore(run) ?? "-"}</strong>
              </div>
              <div>
                <span>质量等级</span>
                <StatusLabel value={getQualityLevel(run)} />
              </div>
            </div>
            {Object.keys(dimScores).length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
                {Object.entries(dimScores).map(([dim, score]) => (
                  <div key={dim} className="flex items-center gap-3">
                    <span style={{ width: 90, fontSize: 12, color: "var(--text-muted)" }}>{dim}</span>
                    <ProgressBar
                      value={score}
                      variant={score >= 80 ? "success" : score >= 60 ? "warning" : "default"}
                      showLabel
                    />
                  </div>
                ))}
              </div>
            )}
            {blockingReasons.length > 0 && (
              <div style={{ marginTop: "var(--space-3)" }}>
                <div className="section-label" style={{ marginBottom: "var(--space-1)" }}>阻断原因</div>
                {blockingReasons.map((r, i) => (
                  <div key={i} style={{ fontSize: 13, color: "var(--error)", marginTop: 4 }}>
                    ❌ {r}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Check items */}
        {checkItems.length > 0 && (
          <div>
            <div className="section-label" style={{ marginBottom: "var(--space-2)" }}>检查项</div>
            <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
              {checkItems.map((item, i) => {
                const status = String(item.status);
                const icon = status === "pass" ? "✓" : status === "fail" ? "✗" : "⚠";
                const color = status === "pass"
                  ? "var(--success)"
                  : status === "fail"
                  ? "var(--error)"
                  : "var(--warning)";
                return (
                  <div key={i} style={{ fontSize: 13, display: "flex", gap: 8 }}>
                    <span style={{ color, width: 16 }}>{icon}</span>
                    <span>{String(item.check_name)}</span>
                    <span className="text-muted">— {String(item.message)}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {run.validation_error && (
          <div style={{ padding: "var(--space-3)", background: "var(--error-50)", borderRadius: "var(--radius-md)", fontSize: 13, color: "var(--error)" }}>
            ❌ 验证错误：{run.validation_error}
          </div>
        )}
      </div>
    </div>
  );
}

export function GovernanceContent({ runs }: { runs: AIGovernanceRun[] }) {
  const [activeTab, setActiveTab] = useState("review");
  const [drawerRun, setDrawerRun] = useState<DrawerRun | null>(null);

  const filtered = filterRuns(runs, activeTab);

  const tabs = queueTabs.map((t) => {
    const count = filterRuns(runs, t.id).length;
    return { ...t, badge: count > 0 ? count : undefined };
  });

  return (
    <>
      <div className="card">
        <div className="card-header">
          <Tabs tabs={tabs} activeTab={activeTab} onTabChange={setActiveTab} />
          <span className="text-xs text-muted">{runs.length} 条记录</span>
        </div>

        <div className="card-body" style={{ padding: 0 }}>
          {filtered.length === 0 ? (
            <div className="empty-state">
              <span className="empty-state-icon">✓</span>
              <strong>此队列暂无项目</strong>
              <p>所有项目已处理完毕</p>
            </div>
          ) : (
            <div>
              {filtered.map((run) => {
                const score = getQualityScore(run);
                const conf = getConfidence(run);
                const cls = getClassification(run);
                const lv = getLevel(run);
                const tags = getTags(run);
                return (
                  <div
                    key={run.id}
                    className="table-row"
                    style={{
                      gridTemplateColumns: "2fr 100px 80px 120px 140px",
                      borderLeft:
                        run.adoption_status === "review_required" ||
                        run.adoption_status === "pending_rule_guardrail"
                          ? "3px solid var(--warning-500)"
                          : "3px solid transparent",
                      cursor: "pointer",
                    }}
                    onClick={() => setDrawerRun({ ...run, _label: getLabel(run) })}
                  >
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 14 }}>
                        {run.normalized_ref_id.slice(0, 12)}…
                      </div>
                      <div className="flex gap-1" style={{ marginTop: 4, flexWrap: "wrap" }}>
                        {cls !== "-" && (
                          <Badge label={cls} variant="brand" />
                        )}
                        {lv !== "-" && (
                          <Badge
                            label={lv}
                            variant={["L3", "L4"].includes(lv) ? "danger" : "neutral"}
                          />
                        )}
                        {tags.slice(0, 2).map((t) => (
                          <span key={t} className="tag">{t}</span>
                        ))}
                      </div>
                    </div>
                    <ConfidenceBadge confidence={conf} />
                    <div className="text-sm text-muted">
                      {run.model_alias.split("/").pop()}
                    </div>
                    {score !== null ? (
                      <ProgressBar
                        value={score}
                        variant={score >= 80 ? "success" : score >= 60 ? "warning" : "default"}
                        showLabel
                      />
                    ) : (
                      <span className="text-muted text-sm">-</span>
                    )}
                    <StatusLabel value={run.adoption_status} />
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {drawerRun && (
        <DecisionDrawer run={drawerRun} onClose={() => setDrawerRun(null)} />
      )}
    </>
  );
}
