"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Drawer,
  Modal,
  Skeleton,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { HistoryOutlined } from "@ant-design/icons";
import { PageHeader } from "@/components/PageHeader";
import {
  fetchGovernanceRules,
  saveGovernanceRules,
  fetchGovernanceRulesVersions,
  fetchGovernanceRulesVersion,
  type GovernanceRules,
  type GovernanceRulesVersion,
  type GovernanceRulesVersionDetail,
  type RecomputeScope,
  type RecomputeSummary,
} from "@/lib/governance-rules-api";
import { RulesEditor } from "./_components/RulesEditor";
import { RulesReadView } from "./_components/RulesReadView";
import { RecomputeSummaryDrawer } from "./_components/RecomputeSummaryDrawer";

type ClassificationRow = {
  code: string;
  name: string;
  criteria: string[];
};

type LevelRow = {
  code: string;
  name: string;
  requires_approval: boolean;
  forbid_external_llm: boolean;
  criteria: string[];
};

type TagRow = {
  code: string;
  name: string;
  applicable_classifications: string[];
  criteria: string[];
};

type DimensionRow = {
  name: string;
  weight: number;
  check_items: unknown[];
  description: string;
};

const DEFAULT_RECOMPUTE_SCOPE: RecomputeScope = "review_required_only";

export default function RulesPage() {
  const { message } = App.useApp();
  const [rules, setRules] = useState<GovernanceRules | null>(null);
  const [editorText, setEditorText] = useState("");
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editorError, setEditorError] = useState<string | null>(null);

  const [recompute, setRecompute] = useState(false);
  const [recomputeScope, setRecomputeScope] = useState<RecomputeScope>(
    DEFAULT_RECOMPUTE_SCOPE,
  );
  const [recomputeSummary, setRecomputeSummary] = useState<RecomputeSummary | null>(
    null,
  );

  // Version history drawer state
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [versions, setVersions] = useState<GovernanceRulesVersion[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [versionDetail, setVersionDetail] = useState<GovernanceRulesVersionDetail | null>(null);
  const [versionDetailOpen, setVersionDetailOpen] = useState(false);

  const loadRules = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    const result = await fetchGovernanceRules();
    if (result.ok) {
      setRules(result.data);
      setEditorText(JSON.stringify(result.data, null, 2));
    } else {
      setLoadError(`无法加载治理规则：${result.error}`);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadRules();
  }, [loadRules]);

  // 编辑态下离开页面前提示，避免丢失未保存的改动
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
    setEditorError(null);
  }

  function handleCancel() {
    setEditing(false);
    setEditorText(JSON.stringify(rules, null, 2));
    setEditorError(null);
    setRecompute(false);
    setRecomputeScope(DEFAULT_RECOMPUTE_SCOPE);
  }

  async function handleSave() {
    setEditorError(null);

    let parsed: GovernanceRules;
    try {
      parsed = JSON.parse(editorText);
    } catch (e) {
      setEditorError(
        "JSON 格式错误：" + (e instanceof Error ? e.message : String(e)),
      );
      return;
    }

    setSaving(true);
    const result = await saveGovernanceRules(parsed, {
      recompute,
      recomputeScope,
    });
    setSaving(false);

    if (result.ok) {
      setRules(parsed);
      setEditing(false);
      setRecomputeSummary(result.summary.recompute ?? null);
      message.success(
        `规则已保存 — 分类 ${result.summary.classifications} / 分级 ${result.summary.levels} / ` +
          `标签 ${result.summary.tags} / 质量维度 ${result.summary.quality_dimensions}`,
      );
      setRecompute(false);
      setRecomputeScope(DEFAULT_RECOMPUTE_SCOPE);
    } else {
      setEditorError(result.error ?? "保存失败");
    }
  }

  async function openVersions() {
    setVersionsOpen(true);
    setVersionsLoading(true);
    const result = await fetchGovernanceRulesVersions();
    if (result.ok) {
      setVersions(result.versions);
    } else {
      message.error(`加载版本历史失败：${result.error}`);
    }
    setVersionsLoading(false);
  }

  async function viewVersionDetail(versionId: string) {
    setVersionDetailOpen(true);
    setVersionDetail(null);
    const result = await fetchGovernanceRulesVersion(versionId);
    if (result.ok) {
      setVersionDetail(result.version);
    } else {
      message.error(`加载版本详情失败：${result.error}`);
      setVersionDetailOpen(false);
    }
  }

  const { classifications, levels, tags, dimensions, thresholds, autoAdoptThreshold } =
    useMemo(() => extractTables(rules), [rules]);

  const versionColumns = [
    { title: "版本号", dataIndex: "version", key: "version", width: 80 },
    { title: "Schema", dataIndex: "schema_version", key: "schema_version", width: 100 },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 90,
      render: (s: string) => (
        <Tag color={s === "active" ? "green" : "default"}>{s}</Tag>
      ),
    },
    { title: "变更摘要", dataIndex: "change_summary", key: "change_summary", ellipsis: true },
    { title: "分类数", dataIndex: "classifications_count", key: "classifications_count", width: 80 },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 170,
      render: (v: string | null) => v ? new Date(v).toLocaleString("zh-CN") : "-",
    },
    {
      title: "操作",
      key: "actions",
      width: 80,
      render: (_: unknown, record: GovernanceRulesVersion) => (
        <Button type="link" size="small" onClick={() => viewVersionDetail(record.id)}>
          查看
        </Button>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        eyebrow="资产与治理 — governance_rules.json"
        title="规则配置"
        description="治理规则定义了 AI 提取元数据时使用的分类、分级、标签和质量评分标准。规则保存后立即生效，可选择对受影响数据触发批量重跑。"
        actions={
          !editing ? (
            <Space>
              <Button
                icon={<HistoryOutlined />}
                onClick={openVersions}
                disabled={loading || !rules}
              >
                版本历史
              </Button>
              <Button
                type="primary"
                onClick={handleEdit}
                disabled={loading || !rules}
              >
                编辑规则
              </Button>
            </Space>
          ) : (
            <Space>
              <Button onClick={handleCancel} disabled={saving}>
                取消
              </Button>
              <Button type="primary" onClick={handleSave} loading={saving}>
                保存并生效
              </Button>
            </Space>
          )
        }
      />

      {loadError && <Alert type="error" showIcon className="mb-4" title={loadError} />}

      <Alert
        className="mb-4"
        type="info"
        showIcon
        title="规则变更保存后立即生效，但默认只影响未来新接入的数据；如需对历史 review_required 资产重跑，请勾选下方的批量重跑选项。"
      />

      {loading ? (
        <Card>
          <Skeleton active paragraph={{ rows: 6 }} />
        </Card>
      ) : editing ? (
        <RulesEditor
          editorText={editorText}
          onChange={setEditorText}
          editorError={editorError}
          recompute={recompute}
          recomputeScope={recomputeScope}
          onRecomputeChange={(e) => setRecompute(e.target.checked)}
          onScopeChange={(v) => setRecomputeScope(v)}
        />
      ) : (
        <RulesReadView
          classifications={classifications}
          levels={levels}
          tags={tags}
          dimensions={dimensions}
          thresholds={thresholds}
          autoAdoptThreshold={autoAdoptThreshold}
        />
      )}

      <RecomputeSummaryDrawer
        summary={recomputeSummary}
        onClose={() => setRecomputeSummary(null)}
      />

      {/* Version history drawer */}
      <Drawer
        title="规则版本历史"
        open={versionsOpen}
        onClose={() => setVersionsOpen(false)}
        width={720}
      >
        <Table
          columns={versionColumns}
          dataSource={versions}
          rowKey="id"
          loading={versionsLoading}
          size="small"
          pagination={false}
        />
      </Drawer>

      {/* Version detail modal */}
      <Modal
        title={
          versionDetail
            ? `版本 v${versionDetail.version} — ${versionDetail.schema_version}`
            : "版本详情"
        }
        open={versionDetailOpen}
        onCancel={() => setVersionDetailOpen(false)}
        footer={null}
        width={800}
      >
        {versionDetail ? (
          <>
            <Space className="mb-4">
              <Tag color={versionDetail.status === "active" ? "green" : "default"}>
                {versionDetail.status}
              </Tag>
              {versionDetail.change_summary && (
                <Typography.Text type="secondary">{versionDetail.change_summary}</Typography.Text>
              )}
            </Space>
            <pre className="max-h-96 overflow-auto rounded bg-gray-50 p-3 text-xs dark:bg-gray-800">
              {JSON.stringify(versionDetail.rules_content, null, 2)}
            </pre>
          </>
        ) : (
          <Skeleton active paragraph={{ rows: 8 }} />
        )}
      </Modal>
    </>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────

interface ExtractedTables {
  classifications: ClassificationRow[];
  levels: LevelRow[];
  tags: TagRow[];
  dimensions: DimensionRow[];
  thresholds: Record<string, unknown> | null;
  autoAdoptThreshold: number | string | null;
}

function extractTables(rules: GovernanceRules | null): ExtractedTables {
  const root = (rules ?? {}) as Record<string, unknown>;

  const classifications = asArray(root.classifications).map((c) => ({
    code: String(c.code ?? ""),
    name: String(c.name ?? ""),
    criteria: asStringArray(c.criteria),
  }));

  const levels = asArray(root.levels).map((l) => ({
    code: String(l.code ?? ""),
    name: String(l.name ?? ""),
    requires_approval: Boolean(l.requires_approval),
    forbid_external_llm: Boolean(l.forbid_external_llm),
    criteria: asStringArray(l.criteria),
  }));

  const tags = asArray(root.tags).map((t) => ({
    code: String(t.code ?? ""),
    name: String(t.name ?? ""),
    applicable_classifications: asStringArray(t.applicable_classifications),
    criteria: asStringArray(t.criteria),
  }));

  const qs = root.quality_scoring as Record<string, unknown> | undefined;
  const dimensions = asArray(qs?.dimensions).map((d) => ({
    name: String(d.name ?? ""),
    weight: Number(d.weight ?? 0),
    check_items: Array.isArray(d.check_items) ? (d.check_items as unknown[]) : [],
    description: String(d.description ?? ""),
  }));

  const thresholds = (qs?.thresholds as Record<string, unknown> | undefined) ?? null;
  const autoAdoptRaw = qs?.confidence_threshold_auto_adopt;
  const autoAdoptThreshold =
    typeof autoAdoptRaw === "number" || typeof autoAdoptRaw === "string"
      ? autoAdoptRaw
      : null;

  return { classifications, levels, tags, dimensions, thresholds, autoAdoptThreshold };
}

function asArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? (value as Record<string, unknown>[]) : [];
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}
