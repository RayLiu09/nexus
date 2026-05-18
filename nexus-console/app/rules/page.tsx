"use client";

import { useState, useEffect, useCallback } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/Badge";
import { apiBaseUrl, postApiData } from "@/lib/api";

type GovernanceRules = Record<string, unknown>;

type RulesSummary = {
  schema_version: string;
  classifications: number;
  levels: number;
  tags: number;
  quality_dimensions: number;
};

async function fetchRules(): Promise<GovernanceRules | null> {
  try {
    const res = await fetch(`${apiBaseUrl()}/v1/admin/governance-rules`, { cache: "no-store" });
    if (!res.ok) return null;
    const json = await res.json();
    return json.data as GovernanceRules;
  } catch {
    return null;
  }
}

async function saveRules(rules: GovernanceRules): Promise<{ ok: boolean; summary?: RulesSummary; error?: string }> {
  try {
    const res = await fetch(`${apiBaseUrl()}/v1/admin/governance-rules`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(rules),
      cache: "no-store",
    });
    const json = await res.json();
    if (!res.ok) {
      return { ok: false, error: json?.detail ?? `HTTP ${res.status}` };
    }
    return { ok: true, summary: json.data as RulesSummary };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

export default function RulesPage() {
  const [rules, setRules] = useState<GovernanceRules | null>(null);
  const [editorText, setEditorText] = useState<string>("");
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  const loadRules = useCallback(async () => {
    setLoading(true);
    setError(null);
    const data = await fetchRules();
    if (data) {
      setRules(data);
      setEditorText(JSON.stringify(data, null, 2));
    } else {
      setError("无法加载治理规则，请检查后端连接");
    }
    setLoading(false);
  }, []);

  useEffect(() => { loadRules(); }, [loadRules]);

  function handleEdit() {
    setEditing(true);
    setValidationError(null);
    setSuccessMsg(null);
  }

  function handleCancel() {
    setEditing(false);
    setEditorText(JSON.stringify(rules, null, 2));
    setValidationError(null);
  }

  function handleEditorChange(val: string) {
    setEditorText(val);
    setValidationError(null);
  }

  async function handleSave() {
    setValidationError(null);
    let parsed: GovernanceRules;
    try {
      parsed = JSON.parse(editorText);
    } catch (e) {
      setValidationError("JSON 格式错误：" + (e instanceof Error ? e.message : String(e)));
      return;
    }
    setSaving(true);
    const result = await saveRules(parsed);
    setSaving(false);
    if (result.ok && result.summary) {
      setRules(parsed);
      setEditing(false);
      setSuccessMsg(
        `规则已保存并立即生效 — 分类: ${result.summary.classifications} 条，` +
        `分级: ${result.summary.levels} 条，标签: ${result.summary.tags} 条，` +
        `质量评分维度: ${result.summary.quality_dimensions} 条`
      );
      setTimeout(() => setSuccessMsg(null), 6000);
    } else {
      setValidationError(result.error ?? "保存失败");
    }
  }

  const classifs = Array.isArray((rules as Record<string, unknown>)?.classifications)
    ? (rules as Record<string, unknown[]>).classifications
    : [];
  const levels = Array.isArray((rules as Record<string, unknown>)?.levels)
    ? (rules as Record<string, unknown[]>).levels
    : [];
  const tags = Array.isArray((rules as Record<string, unknown>)?.tags)
    ? (rules as Record<string, unknown[]>).tags
    : [];
  const dims = Array.isArray(
    ((rules as Record<string, unknown>)?.quality_scoring as Record<string, unknown>)?.dimensions
  )
    ? (
        ((rules as Record<string, unknown>)?.quality_scoring as Record<string, unknown[]>)
          .dimensions
      )
    : [];

  return (
    <>
      <PageHeader
        prototypeId="NX-09"
        title="规则配置"
        description="治理规则定义了 AI 提取元数据时使用的分类、分级、标签和质量评分标准。规则保存后立即生效，仅影响未来接入资产。"
        actions={
          !editing ? (
            <button className="btn btn-primary btn-sm" onClick={handleEdit} disabled={loading || !rules}>
              ✏️ 编辑规则
            </button>
          ) : (
            <div className="flex gap-2">
              <button className="btn btn-ghost btn-sm" onClick={handleCancel} disabled={saving}>取消</button>
              <button className="btn btn-primary btn-sm" onClick={handleSave} disabled={saving}>
                {saving ? "保存中..." : "保存并生效"}
              </button>
            </div>
          )
        }
      />

      {successMsg && (
        <div className="notice notice-success">✅ {successMsg}</div>
      )}
      {error && (
        <div className="notice notice-error">⚠️ {error}</div>
      )}

      <div className="notice notice-info">
        ⓘ 规则变更保存后立即生效，仅对未来新接入的数据资产生效。已完成治理的历史资产不受影响。如需对历史资产重应用规则，请使用治理中心的批量重治理功能。
      </div>

      {loading ? (
        <div className="card">
          <div className="card-body" style={{ textAlign: "center", padding: "var(--space-8)" }}>
            <span className="text-muted">加载规则中...</span>
          </div>
        </div>
      ) : editing ? (
        /* Editor mode */
        <div className="card">
          <div className="card-header">
            <span className="card-title">编辑 governance_rules.json</span>
            <Badge label="编辑中" variant="warning" />
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            <textarea
              value={editorText}
              onChange={(e) => handleEditorChange(e.target.value)}
              style={{
                width: "100%",
                minHeight: 480,
                fontFamily: "var(--font-mono)",
                fontSize: 13,
                lineHeight: 1.6,
                padding: "var(--space-4)",
                border: "none",
                outline: "none",
                background: "var(--gray-900)",
                color: "#e5e7eb",
                borderRadius: "0 0 var(--radius-lg) var(--radius-lg)",
                resize: "vertical",
              }}
              spellCheck={false}
            />
          </div>
          {validationError && (
            <div className="card-footer">
              <span className="text-sm" style={{ color: "var(--error)" }}>❌ {validationError}</span>
            </div>
          )}
        </div>
      ) : (
        /* Read mode — structured summary cards */
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>

          {/* Classifications */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">数据域分类（classification）</span>
              <Badge label={`${classifs.length} 条`} variant="brand" />
            </div>
            <div className="card-body">
              <table className="table" style={{ width: "100%" }}>
                <thead>
                  <tr>
                    <th>Code</th><th>名称</th><th>判断标准（criteria）</th>
                  </tr>
                </thead>
                <tbody>
                  {(classifs as Record<string, unknown>[]).map((c) => (
                    <tr key={String(c.code)}>
                      <td><Badge label={String(c.code)} variant="brand" /></td>
                      <td>{String(c.name)}</td>
                      <td style={{ fontSize: 12, color: "var(--text-muted)" }}>
                        {Array.isArray(c.criteria)
                          ? (c.criteria as string[]).join("；")
                          : "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Levels */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">数据分级（level）</span>
              <Badge label={`${levels.length} 条`} variant="brand" />
            </div>
            <div className="card-body">
              <table className="table" style={{ width: "100%" }}>
                <thead>
                  <tr>
                    <th>Code</th><th>名称</th><th>需审批</th><th>判断标准</th>
                  </tr>
                </thead>
                <tbody>
                  {(levels as Record<string, unknown>[]).map((l) => (
                    <tr key={String(l.code)}>
                      <td><Badge label={String(l.code)} variant={l.code === "L3" || l.code === "L4" ? "danger" : "neutral"} /></td>
                      <td>{String(l.name)}</td>
                      <td>{l.requires_approval ? "是" : "否"}</td>
                      <td style={{ fontSize: 12, color: "var(--text-muted)" }}>
                        {Array.isArray(l.criteria) ? (l.criteria as string[]).join("；") : "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Tags */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">数据标签（tags）</span>
              <Badge label={`${tags.length} 条`} variant="brand" />
            </div>
            <div className="card-body">
              <table className="table" style={{ width: "100%" }}>
                <thead>
                  <tr>
                    <th>Code</th><th>名称</th><th>适用分类</th><th>判断标准</th>
                  </tr>
                </thead>
                <tbody>
                  {(tags as Record<string, unknown>[]).map((t) => (
                    <tr key={String(t.code)}>
                      <td><Badge label={String(t.code)} variant="neutral" /></td>
                      <td>{String(t.name)}</td>
                      <td style={{ fontSize: 12 }}>
                        {Array.isArray(t.applicable_classifications) && (t.applicable_classifications as string[]).length > 0
                          ? (t.applicable_classifications as string[]).join(", ")
                          : "通用"}
                      </td>
                      <td style={{ fontSize: 12, color: "var(--text-muted)" }}>
                        {Array.isArray(t.criteria) ? (t.criteria as string[]).join("；") : "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Quality scoring */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">质量评分维度（quality_scoring）</span>
              <Badge label={`${dims.length} 维度`} variant="brand" />
            </div>
            <div className="card-body">
              <table className="table" style={{ width: "100%" }}>
                <thead>
                  <tr>
                    <th>维度</th><th>权重</th><th>检查项数</th><th>说明</th>
                  </tr>
                </thead>
                <tbody>
                  {(dims as Record<string, unknown>[]).map((d) => (
                    <tr key={String(d.name)}>
                      <td><strong>{String(d.name)}</strong></td>
                      <td>{(Number(d.weight) * 100).toFixed(0)}%</td>
                      <td>{Array.isArray(d.check_items) ? (d.check_items as unknown[]).length : 0}</td>
                      <td style={{ fontSize: 12, color: "var(--text-muted)" }}>{String(d.description ?? "-")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {rules && typeof (rules as Record<string, unknown>).quality_scoring === "object" && (
                <div style={{ marginTop: "var(--space-3)", fontSize: 13, color: "var(--text-muted)" }}>
                  通过阈值：≥{String(
                    ((rules as Record<string, unknown>).quality_scoring as Record<string, unknown>)?.thresholds
                      ? (((rules as Record<string, unknown>).quality_scoring as Record<string, unknown>).thresholds as Record<string, unknown>).pass
                      : "-"
                  )} 分 &nbsp;|&nbsp;
                  预警阈值：≥{String(
                    ((rules as Record<string, unknown>).quality_scoring as Record<string, unknown>)?.thresholds
                      ? (((rules as Record<string, unknown>).quality_scoring as Record<string, unknown>).thresholds as Record<string, unknown>).warning
                      : "-"
                  )} 分 &nbsp;|&nbsp;
                  AI 自动采纳置信度阈值：{String(
                    ((rules as Record<string, unknown>).quality_scoring as Record<string, unknown>)
                      ?.confidence_threshold_auto_adopt ?? "-"
                  )}
                </div>
              )}
            </div>
          </div>

        </div>
      )}
    </>
  );
}
