"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  Badge,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Drawer,
  Modal,
  Radio,
  Skeleton,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { CheckboxChangeEvent } from "antd/es/checkbox";
import type { ColumnsType } from "antd/es/table";
import { PageHeader } from "@/components/PageHeader";
import {
  fetchGovernanceRules,
  saveGovernanceRules,
  type GovernanceRules,
  type RecomputeScope,
  type RecomputeSummary,
} from "@/lib/governance-rules-api";

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
  const [etag, setEtag] = useState("");
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

  const loadRules = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    const result = await fetchGovernanceRules();
    if (result.ok) {
      setRules(result.data);
      setEditorText(JSON.stringify(result.data, null, 2));
      setEtag(result.etag);
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
    const result = await saveGovernanceRules(parsed, etag, {
      recompute,
      recomputeScope,
    });
    setSaving(false);

    if (result.ok) {
      setRules(parsed);
      setEtag(result.etag);
      setEditing(false);
      setRecomputeSummary(result.summary.recompute ?? null);
      message.success(
        `规则已保存 — 分类 ${result.summary.classifications} / 分级 ${result.summary.levels} / ` +
          `标签 ${result.summary.tags} / 质量维度 ${result.summary.quality_dimensions}`,
      );
      // 关闭后重置勾选，避免下次编辑无意触发批量重跑
      setRecompute(false);
      setRecomputeScope(DEFAULT_RECOMPUTE_SCOPE);
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
      setEditorError(result.error ?? "保存失败");
    }
  }

  const { classifications, levels, tags, dimensions, thresholds, autoAdoptThreshold } =
    useMemo(() => extractTables(rules), [rules]);

  return (
    <>
      <PageHeader
        eyebrow="资产与治理 — governance_rules.json"
        title="规则配置"
        description="治理规则定义了 AI 提取元数据时使用的分类、分级、标签和质量评分标准。规则保存后立即生效，可选择对受影响数据触发批量重跑。"
        actions={
          !editing ? (
            <Button
              type="primary"
              onClick={handleEdit}
              disabled={loading || !rules}
            >
              编辑规则
            </Button>
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

      {loadError && <Alert type="error" showIcon className="mb-4" message={loadError} />}

      <Alert
        className="mb-4"
        type="info"
        showIcon
        message="规则变更保存后立即生效，但默认只影响未来新接入的数据；如需对历史 review_required 资产重跑，请勾选下方的批量重跑选项。"
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
          onRecomputeChange={(e: CheckboxChangeEvent) => setRecompute(e.target.checked)}
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
    </>
  );
}

// ── Editor ───────────────────────────────────────────────────────────────

interface RulesEditorProps {
  editorText: string;
  onChange: (val: string) => void;
  editorError: string | null;
  recompute: boolean;
  recomputeScope: RecomputeScope;
  onRecomputeChange: (e: CheckboxChangeEvent) => void;
  onScopeChange: (v: RecomputeScope) => void;
}

function RulesEditor({
  editorText,
  onChange,
  editorError,
  recompute,
  recomputeScope,
  onRecomputeChange,
  onScopeChange,
}: RulesEditorProps) {
  return (
    <Space direction="vertical" size="middle" className="w-full">
      <Card
        title={
          <Space>
            <span>编辑 governance_rules.json</span>
            <Tag color="warning">编辑中</Tag>
          </Space>
        }
        styles={{ body: { padding: 0 } }}
      >
        <textarea
          value={editorText}
          onChange={(e) => onChange(e.target.value)}
          className="block w-full min-h-[480px] resize-y border-none p-4 font-mono text-[13px] leading-relaxed outline-none rounded-b-lg bg-[var(--gray-900)] text-[#e5e7eb]"
          spellCheck={false}
          aria-label="governance_rules.json 编辑器"
        />
        {editorError && (
          <Alert
            className="m-3"
            type="error"
            showIcon
            message={editorError}
          />
        )}
      </Card>

      <Card title="保存选项 — 批量重跑（Review §5.4）">
        <Space direction="vertical" size="small">
          <Checkbox checked={recompute} onChange={onRecomputeChange}>
            保存后对受影响的数据触发批量重跑
          </Checkbox>
          <Typography.Paragraph
            type="secondary"
            className="!mb-0 text-[12px]"
          >
            勾选后，本次规则变更命中的 normalized_ref 会按下方范围重新调度治理。AVAILABLE
            版本不会被自动改写（仅写入审计），避免破坏已发布索引。
          </Typography.Paragraph>
          <Radio.Group
            disabled={!recompute}
            value={recomputeScope}
            onChange={(e) => onScopeChange(e.target.value)}
            optionType="default"
          >
            <Space direction="vertical">
              <Radio value="review_required_only">
                仅 <code>review_required</code> 版本回流到 processing（默认 / 较安全）
              </Radio>
              <Radio value="all_affected">
                包含 <code>available</code>：仍只把 review_required 版本回流，
                额外把 available 版本登记到审计日志，便于人工逐条决定是否重跑
              </Radio>
            </Space>
          </Radio.Group>
        </Space>
      </Card>
    </Space>
  );
}

// ── Read view ────────────────────────────────────────────────────────────

interface RulesReadViewProps {
  classifications: ClassificationRow[];
  levels: LevelRow[];
  tags: TagRow[];
  dimensions: DimensionRow[];
  thresholds: Record<string, unknown> | null;
  autoAdoptThreshold: number | string | null;
}

function RulesReadView({
  classifications,
  levels,
  tags,
  dimensions,
  thresholds,
  autoAdoptThreshold,
}: RulesReadViewProps) {
  return (
    <Space direction="vertical" size="middle" className="w-full">
      <Card
        title={
          <Space>
            <span>数据域分类（classification）</span>
            <Badge count={classifications.length} color="var(--brand)" />
          </Space>
        }
      >
        <Table<ClassificationRow>
          rowKey="code"
          dataSource={classifications}
          pagination={false}
          size="middle"
          columns={CLASSIFICATION_COLUMNS}
        />
      </Card>

      <Card
        title={
          <Space>
            <span>数据分级（level）</span>
            <Badge count={levels.length} color="var(--brand)" />
          </Space>
        }
      >
        <Table<LevelRow>
          rowKey="code"
          dataSource={levels}
          pagination={false}
          size="middle"
          columns={LEVEL_COLUMNS}
        />
      </Card>

      <Card
        title={
          <Space>
            <span>数据标签（tags）</span>
            <Badge count={tags.length} color="var(--brand)" />
          </Space>
        }
      >
        <Table<TagRow>
          rowKey="code"
          dataSource={tags}
          pagination={false}
          size="middle"
          columns={TAG_COLUMNS}
        />
      </Card>

      <Card
        title={
          <Space>
            <span>质量评分维度（quality_scoring）</span>
            <Badge count={dimensions.length} color="var(--brand)" />
          </Space>
        }
      >
        <Table<DimensionRow>
          rowKey="name"
          dataSource={dimensions}
          pagination={false}
          size="middle"
          columns={DIMENSION_COLUMNS}
        />
        {thresholds && (
          <Typography.Paragraph
            type="secondary"
            className="!mt-3 !mb-0 text-[13px]"
          >
            通过阈值：≥{String(thresholds.pass ?? "-")} 分 ｜ 预警：≥
            {String(thresholds.warning ?? "-")} 分 ｜ 复核线：&lt;
            {String(thresholds.review_required_below ?? "-")} 分 ｜ AI 自动采纳置信度：
            {autoAdoptThreshold ?? "-"}
          </Typography.Paragraph>
        )}
      </Card>
    </Space>
  );
}

const CLASSIFICATION_COLUMNS: ColumnsType<ClassificationRow> = [
  {
    title: "Code",
    dataIndex: "code",
    width: 110,
    render: (code: string) => <Tag color="purple">{code}</Tag>,
  },
  { title: "名称", dataIndex: "name", width: 200 },
  {
    title: "判断标准",
    dataIndex: "criteria",
    render: (criteria: string[]) =>
      criteria.length > 0 ? (
        <span className="text-xs text-[var(--text-muted)]">{criteria.join("；")}</span>
      ) : (
        "-"
      ),
  },
];

const LEVEL_COLUMNS: ColumnsType<LevelRow> = [
  {
    title: "Code",
    dataIndex: "code",
    width: 90,
    render: (code: string) => {
      const dangerous = code === "L3" || code === "L4";
      return <Tag color={dangerous ? "error" : "default"}>{code}</Tag>;
    },
  },
  { title: "名称", dataIndex: "name", width: 180 },
  {
    title: "需审批",
    dataIndex: "requires_approval",
    width: 90,
    render: (v: boolean) => (v ? "是" : "否"),
  },
  {
    title: "禁外部 LLM",
    dataIndex: "forbid_external_llm",
    width: 110,
    render: (v: boolean) => (v ? "是" : "-"),
  },
  {
    title: "判断标准",
    dataIndex: "criteria",
    render: (criteria: string[]) =>
      criteria.length > 0 ? (
        <span className="text-xs text-[var(--text-muted)]">{criteria.join("；")}</span>
      ) : (
        "-"
      ),
  },
];

const TAG_COLUMNS: ColumnsType<TagRow> = [
  {
    title: "Code",
    dataIndex: "code",
    width: 140,
    render: (code: string) => <Tag>{code}</Tag>,
  },
  { title: "名称", dataIndex: "name", width: 180 },
  {
    title: "适用分类",
    dataIndex: "applicable_classifications",
    width: 200,
    render: (xs: string[]) =>
      xs.length > 0 ? (
        <span className="text-xs">{xs.join(", ")}</span>
      ) : (
        <span className="text-xs text-[var(--text-muted)]">通用</span>
      ),
  },
  {
    title: "判断标准",
    dataIndex: "criteria",
    render: (criteria: string[]) =>
      criteria.length > 0 ? (
        <span className="text-xs text-[var(--text-muted)]">{criteria.join("；")}</span>
      ) : (
        "-"
      ),
  },
];

const DIMENSION_COLUMNS: ColumnsType<DimensionRow> = [
  {
    title: "维度",
    dataIndex: "name",
    width: 160,
    render: (n: string) => <strong>{n}</strong>,
  },
  {
    title: "权重",
    dataIndex: "weight",
    width: 90,
    render: (w: number) => `${(w * 100).toFixed(0)}%`,
  },
  {
    title: "检查项数",
    dataIndex: "check_items",
    width: 100,
    render: (items: unknown[]) => items.length,
  },
  {
    title: "说明",
    dataIndex: "description",
    render: (d: string) => (
      <span className="text-xs text-[var(--text-muted)]">{d || "-"}</span>
    ),
  },
];

// ── Recompute Summary Drawer ─────────────────────────────────────────────

function RecomputeSummaryDrawer({
  summary,
  onClose,
}: {
  summary: RecomputeSummary | null;
  onClose: () => void;
}) {
  return (
    <Drawer
      title="批量重跑结果"
      width={520}
      open={summary !== null}
      onClose={onClose}
      destroyOnClose
    >
      {summary && (
        <Space direction="vertical" size="middle" className="w-full">
          <Descriptions bordered size="small" column={1}>
            <Descriptions.Item label="重跑范围">
              <Tag color="processing">{summary.scope}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="受影响 normalized_ref 总数">
              {summary.affected_total}
            </Descriptions.Item>
            <Descriptions.Item label="已回流到 processing 的版本数">
              <Tag color="success">{summary.rescheduled_count}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="保留 available 不变（仅审计）">
              <Tag color="default">{summary.available_skipped_count}</Tag>
            </Descriptions.Item>
          </Descriptions>

          <VersionIdList
            title="被重新调度的版本"
            ids={summary.rescheduled_version_ids}
            emptyLabel="无"
          />
          <VersionIdList
            title="登记审计但未自动重跑的 available 版本"
            ids={summary.available_skipped_version_ids}
            emptyLabel="无"
          />
        </Space>
      )}
    </Drawer>
  );
}

function VersionIdList({
  title,
  ids,
  emptyLabel,
}: {
  title: string;
  ids: string[];
  emptyLabel: string;
}) {
  return (
    <div>
      <Typography.Text strong>{title}</Typography.Text>
      <div className="mt-2">
        {ids.length === 0 ? (
          <Typography.Text type="secondary">{emptyLabel}</Typography.Text>
        ) : (
          <Space size={4} wrap>
            {ids.map((id) => (
              <Tag key={id} className="font-mono" style={{ fontSize: 12 }}>
                {id}
              </Tag>
            ))}
          </Space>
        )}
      </div>
    </div>
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
