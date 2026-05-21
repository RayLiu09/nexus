"use client";

import { useState, useEffect, useCallback } from "react";
import { Modal, message } from "antd";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/Badge";
import {
  fetchGovernanceRules,
  saveGovernanceRules,
  type GovernanceRules,
} from "@/lib/governance-rules-api";

export default function RulesPage() {
  const [rules, setRules] = useState<GovernanceRules | null>(null);
  const [editorText, setEditorText] = useState("");
  const [etag, setEtag] = useState("");
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  const loadRules = useCallback(async () => {
    setLoading(true);
    setError(null);
    const result = await fetchGovernanceRules();
    if (result.ok) {
      setRules(result.data);
      setEditorText(JSON.stringify(result.data, null, 2));
      setEtag(result.etag);
    } else {
      setError("无法加载治理规则，请检查后端连接");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadRules();
  }, [loadRules]);

  useEffect(() => {
    if (!editing) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [editing]);

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
    const result = await saveGovernanceRules(parsed, etag);
    setSaving(false);

    if (result.ok) {
      setRules(parsed);
      setEtag(result.etag);
      setEditing(false);
      message.success(
        `规则已保存 — 分类: ${result.summary.classifications}，` +
        `分级: ${result.summary.levels}，标签: ${result.summary.tags}，` +
        `质量维度: ${result.summary.quality_dimensions}`,
      );
    } else if (result.status === 409) {
      Modal.confirm({
        title: "规则已被他人更新",
        content: "另一位管理员在您编辑期间修改了治理规则。请重新加载最新版本后再编辑。",
        okText: "重新加载",
        cancelText: "取消",
        onOk: async () => {
          await loadRules();
          setEditing(false);
        },
      });
    } else {
      setValidationError(result.error ?? "保存失败");
    }
  }

  const classifs = (Array.isArray((rules as Record<string, unknown>)?.classifications)
    ? (rules as Record<string, unknown[]>).classifications : []) as Record<string, unknown>[];
  const levels = (Array.isArray((rules as Record<string, unknown>)?.levels)
    ? (rules as Record<string, unknown[]>).levels : []) as Record<string, unknown>[];
  const tags = (Array.isArray((rules as Record<string, unknown>)?.tags)
    ? (rules as Record<string, unknown[]>).tags : []) as Record<string, unknown>[];
  const dims = (Array.isArray(
    ((rules as Record<string, unknown>)?.quality_scoring as Record<string, unknown>)?.dimensions,
  ) ? ((rules as Record<string, unknown>)?.quality_scoring as Record<string, unknown[]>).dimensions : []) as Record<string, unknown>[];

  return (
    <>
      <PageHeader
        eyebrow="资产与治理 — governance_rules.json"
        title="规则配置"
        description="治理规则定义了 AI 提取元数据时使用的分类、分级、标签和质量评分标准。规则保存后立即生效，仅影响未来接入资产。"
        actions={
          !editing ? (
            <button className="btn btn-primary btn-sm" onClick={handleEdit} disabled={loading || !rules}>
              编辑规则
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

      {successMsg && <div className="notice notice-success">{successMsg}</div>}
      {error && <div className="notice notice-error">{error}</div>}

      <div className="notice notice-info">
        规则变更保存后立即生效，仅对未来新接入的数据资产生效。已完成治理的历史资产不受影响。
      </div>

      {loading ? (
        <div className="card">
          <div className="card-body text-center py-8">
            <span className="text-muted">加载规则中...</span>
          </div>
        </div>
      ) : editing ? (
        <div className="card">
          <div className="card-header">
            <span className="card-title">编辑 governance_rules.json</span>
            <Badge label="编辑中" variant="warning" />
          </div>
          <div className="card-body p-0">
            <textarea
              value={editorText}
              onChange={(e) => handleEditorChange(e.target.value)}
              className="w-full min-h-[480px] font-mono text-[13px] leading-relaxed p-4 border-none outline-none bg-[var(--gray-900)] text-[#e5e7eb] rounded-b-lg resize-y"
              spellCheck={false}
            />
          </div>
          {validationError && (
            <div className="card-footer">
              <span className="text-sm text-[var(--danger-600)]">{validationError}</span>
            </div>
          )}
        </div>
      ) : (
        <RulesReadView classifs={classifs} levels={levels} tags={tags} dims={dims} rules={rules} />
      )}
    </>
  );
}

type ReadViewProps = {
  classifs: Record<string, unknown>[];
  levels: Record<string, unknown>[];
  tags: Record<string, unknown>[];
  dims: Record<string, unknown>[];
  rules: GovernanceRules | null;
};

function RulesReadView({ classifs, levels, tags, dims, rules }: ReadViewProps) {
  const qs = (rules as Record<string, unknown>)?.quality_scoring as Record<string, unknown> | undefined;
  const thresholds = qs?.thresholds as Record<string, unknown> | undefined;

  return (
    <div className="flex flex-col gap-4">
      <SummaryTable title="数据域分类（classification）" count={classifs.length} headers={["Code", "名称", "判断标准"]}>
        {classifs.map((c) => (
          <tr key={String(c.code)}>
            <td><Badge label={String(c.code)} variant="brand" /></td>
            <td>{String(c.name)}</td>
            <td className="text-xs text-[var(--text-muted)]">
              {Array.isArray(c.criteria) ? (c.criteria as string[]).join("；") : "-"}
            </td>
          </tr>
        ))}
      </SummaryTable>

      <SummaryTable title="数据分级（level）" count={levels.length} headers={["Code", "名称", "需审批", "禁外部LLM", "判断标准"]}>
        {levels.map((l) => (
          <tr key={String(l.code)}>
            <td><Badge label={String(l.code)} variant={l.code === "L3" || l.code === "L4" ? "danger" : "neutral"} /></td>
            <td>{String(l.name)}</td>
            <td>{l.requires_approval ? "是" : "否"}</td>
            <td>{l.forbid_external_llm ? "是" : "-"}</td>
            <td className="text-xs text-[var(--text-muted)]">
              {Array.isArray(l.criteria) ? (l.criteria as string[]).join("；") : "-"}
            </td>
          </tr>
        ))}
      </SummaryTable>

      <SummaryTable title="数据标签（tags）" count={tags.length} headers={["Code", "名称", "适用分类", "判断标准"]}>
        {tags.map((t) => (
          <tr key={String(t.code)}>
            <td><Badge label={String(t.code)} variant="neutral" /></td>
            <td>{String(t.name)}</td>
            <td className="text-xs">
              {Array.isArray(t.applicable_classifications) && (t.applicable_classifications as string[]).length > 0
                ? (t.applicable_classifications as string[]).join(", ") : "通用"}
            </td>
            <td className="text-xs text-[var(--text-muted)]">
              {Array.isArray(t.criteria) ? (t.criteria as string[]).join("；") : "-"}
            </td>
          </tr>
        ))}
      </SummaryTable>

      <div className="card">
        <div className="card-header">
          <span className="card-title">质量评分维度（quality_scoring）</span>
          <Badge label={`${dims.length} 维度`} variant="brand" />
        </div>
        <div className="card-body">
          <table className="table w-full">
            <thead><tr><th>维度</th><th>权重</th><th>检查项数</th><th>说明</th></tr></thead>
            <tbody>
              {dims.map((d) => (
                <tr key={String(d.name)}>
                  <td><strong>{String(d.name)}</strong></td>
                  <td>{(Number(d.weight) * 100).toFixed(0)}%</td>
                  <td>{Array.isArray(d.check_items) ? (d.check_items as unknown[]).length : 0}</td>
                  <td className="text-xs text-[var(--text-muted)]">{String(d.description ?? "-")}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {thresholds && (
            <div className="mt-3 text-[13px] text-[var(--text-muted)]">
              通过阈值：≥{String(thresholds.pass ?? "-")} 分 | 预警：≥{String(thresholds.warning ?? "-")} 分 | 复核线：&lt;{String(thresholds.review_required_below ?? "-")} 分 | AI 自动采纳置信度：{String(qs?.confidence_threshold_auto_adopt ?? "-")}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function SummaryTable({ title, count, headers, children }: {
  title: string; count: number; headers: string[]; children: React.ReactNode;
}) {
  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">{title}</span>
        <Badge label={`${count} 条`} variant="brand" />
      </div>
      <div className="card-body">
        <table className="table w-full">
          <thead><tr>{headers.map((h) => <th key={h}>{h}</th>)}</tr></thead>
          <tbody>{children}</tbody>
        </table>
      </div>
    </div>
  );
}
