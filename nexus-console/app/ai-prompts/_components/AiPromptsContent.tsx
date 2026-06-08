"use client";

import { useState } from "react";
import { Button, Drawer, Tag, Descriptions, App, Input, InputNumber, Select, Alert } from "antd";
import { PlusOutlined, EditOutlined, CopyOutlined, StopOutlined, ExperimentOutlined } from "@ant-design/icons";
import { Empty } from "antd";
import { formatTime } from "@/lib/format-time";
import { postApiData, putApiData } from "@/lib/api";

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

const MOCK_FALLBACK: PromptProfile[] = [
  {
    id: "pp-1",
    profile_name: "元数据治理",
    profile_version: 3,
    task_type: "metadata_governance",
    status: "active",
    litellm_model_alias: "LiteLLM/qwen-plus",
    prompt_version: "v3",
    output_schema_version: "1.0",
    scoring_weight_version: "1.0",
    temperature: 0.3,
    max_input_tokens: 4096,
    redaction_policy: "masked_content",
    created_at: "2026-05-07T10:00:00Z",
    updated_at: "2026-05-14T08:23:00Z",
  },
  {
    id: "pp-2",
    profile_name: "质量评分",
    profile_version: 2,
    task_type: "quality_scoring",
    status: "active",
    litellm_model_alias: "LiteLLM/deepseek-v3",
    prompt_version: "v2",
    output_schema_version: "1.0",
    scoring_weight_version: "1.0",
    temperature: 0.2,
    max_input_tokens: 4096,
    redaction_policy: "metadata_only",
    created_at: "2026-05-01T10:00:00Z",
    updated_at: "2026-05-10T14:00:00Z",
  },
  {
    id: "pp-3",
    profile_name: "敏感复核",
    profile_version: 1,
    task_type: "sensitive_review",
    status: "active",
    litellm_model_alias: "LiteLLM/qwen-plus",
    prompt_version: "v1",
    output_schema_version: "1.0",
    scoring_weight_version: "1.0",
    temperature: 0.1,
    max_input_tokens: 2048,
    redaction_policy: "full_content_private",
    created_at: "2026-05-01T10:00:00Z",
    updated_at: "2026-05-08T11:00:00Z",
  },
];

// PLACEHOLDER_REST

const TASK_TYPES = [
  { value: "metadata_governance", label: "元数据治理" },
  { value: "quality_scoring", label: "质量评分" },
  { value: "sensitive_review", label: "敏感复核" },
  { value: "tag_generation", label: "标签生成" },
];

const REDACTION_POLICIES = [
  { value: "masked_content", label: "内容脱敏" },
  { value: "metadata_only", label: "仅元数据" },
  { value: "full_content_private", label: "全内容私有" },
];

function redactionTag(policy: string) {
  const map: Record<string, { color: string; label: string }> = {
    masked_content: { color: "processing", label: "内容脱敏" },
    metadata_only: { color: "default", label: "仅元数据" },
    full_content_private: { color: "error", label: "全内容私有" },
  };
  const m = map[policy] ?? { color: "default", label: policy };
  return <Tag color={m.color}>{m.label}</Tag>;
}

function statusTag(status: string) {
  return status === "active" ? (
    <Tag color="success">已生效</Tag>
  ) : (
    <Tag color="default">已禁用</Tag>
  );
}

type FormState = {
  profile_name: string;
  task_type: string;
  litellm_model_alias: string;
  prompt_version: string;
  output_schema_version: string;
  scoring_weight_version: string;
  temperature: number;
  max_input_tokens: number;
  redaction_policy: string;
};

const DEFAULT_FORM: FormState = {
  profile_name: "",
  task_type: "metadata_governance",
  litellm_model_alias: "LiteLLM/qwen-plus",
  prompt_version: "v1",
  output_schema_version: "1.0",
  scoring_weight_version: "1.0",
  temperature: 0.3,
  max_input_tokens: 4096,
  redaction_policy: "masked_content",
};

export default function AiPromptsContent({ profiles }: { profiles: PromptProfile[] }) {
  const isDemo = profiles.length === 0;
  const data = isDemo ? MOCK_FALLBACK : profiles;
  const [items, setItems] = useState<PromptProfile[]>(data);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [saving, setSaving] = useState(false);
  const { message, modal } = App.useApp();

  const openCreate = () => {
    setEditingId(null);
    setForm(DEFAULT_FORM);
    setDrawerOpen(true);
  };

  const openEdit = (p: PromptProfile) => {
    setEditingId(p.id);
    setForm({
      profile_name: p.profile_name,
      task_type: p.task_type,
      litellm_model_alias: p.litellm_model_alias,
      prompt_version: p.prompt_version,
      output_schema_version: p.output_schema_version,
      scoring_weight_version: p.scoring_weight_version,
      temperature: p.temperature,
      max_input_tokens: p.max_input_tokens,
      redaction_policy: p.redaction_policy,
    });
    setDrawerOpen(true);
  };

  const openClone = (p: PromptProfile) => {
    setEditingId(null);
    setForm({
      profile_name: `${p.profile_name} (副本)`,
      task_type: p.task_type,
      litellm_model_alias: p.litellm_model_alias,
      prompt_version: `v${p.profile_version + 1}`,
      output_schema_version: p.output_schema_version,
      scoring_weight_version: p.scoring_weight_version,
      temperature: p.temperature,
      max_input_tokens: p.max_input_tokens,
      redaction_policy: p.redaction_policy,
    });
    setDrawerOpen(true);
  };

  const handleSave = async () => {
    if (!form.profile_name.trim()) {
      message.warning("请填写配置名称");
      return;
    }
    setSaving(true);
    try {
      if (editingId) {
        const result = await putApiData<PromptProfile>(
          `/v1/ai/prompt-profiles/${editingId}`,
          form as unknown as Record<string, unknown>,
        );
        setItems((prev) => prev.map((p) => (p.id === editingId ? { ...p, ...result.data } : p)));
        message.success("配置已更新");
      } else {
        const result = await postApiData<PromptProfile>(
          "/v1/ai/prompt-profiles",
          form as unknown as Record<string, unknown>,
        );
        setItems((prev) => [result.data, ...prev]);
        message.success("配置已创建");
      }
      setDrawerOpen(false);
    } catch (e) {
      message.error(`保存失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  };

  const handleDisable = (p: PromptProfile) => {
    modal.confirm({
      title: `确认禁用「${p.profile_name}」？`,
      content: "禁用后此配置不再参与 AI 治理选用。已使用此配置产生的历史治理记录不受影响。",
      okText: "确认禁用",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        try {
          await postApiData<void>(`/v1/ai/prompt-profiles/${p.id}/disable`, {});
          setItems((prev) => prev.map((x) => (x.id === p.id ? { ...x, status: "disabled" } : x)));
          message.success("已禁用");
        } catch (e) {
          message.error(`禁用失败：${e instanceof Error ? e.message : String(e)}`);
        }
      },
    });
  };

  return (
    <>
      {/* Toolbar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 16,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>
            {items.length} 个配置 · {items.filter((p) => p.status === "active").length} 个生效中
          </span>
          {isDemo && (
            <Alert
              type="warning"
              showIcon
              icon={<ExperimentOutlined />}
              title="演示数据"
              className="!mb-0 !py-0.5 !px-2.5 text-xs"
            />
          )}
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建配置
        </Button>
      </div>

      {/* Profile Cards */}
      {items.length === 0 ? (
        <Empty description="暂无 Prompt 配置" />
      ) : (
        <div style={{ display: "grid", gap: 12 }}>
          {items.map((p) => {
            const { display } = formatTime(p.updated_at);
            return (
              <div
                key={p.id}
                style={{
                  background: "var(--surface)",
                  border: "1px solid var(--line)",
                  borderLeft:
                    p.status === "active"
                      ? "3px solid var(--success-600)"
                      : "3px solid var(--line-strong)",
                  borderRadius: "var(--radius-xl)",
                  padding: "16px 20px",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                  }}
                >
                  <div>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        marginBottom: 6,
                      }}
                    >
                      <strong style={{ fontSize: 15 }}>{p.profile_name}</strong>
                      <Tag color="blue">{p.task_type}</Tag>
                      <Tag>v{p.profile_version}</Tag>
                      {statusTag(p.status)}
                    </div>
                    <Descriptions size="small" column={4}>
                      <Descriptions.Item label="模型">
                        <code style={{ fontSize: 12 }}>{p.litellm_model_alias}</code>
                      </Descriptions.Item>
                      <Descriptions.Item label="Temperature">{p.temperature}</Descriptions.Item>
                      <Descriptions.Item label="Max Tokens">{p.max_input_tokens}</Descriptions.Item>
                      <Descriptions.Item label="脱敏">
                        {redactionTag(p.redaction_policy)}
                      </Descriptions.Item>
                    </Descriptions>
                  </div>
                  <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                    <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(p)}>
                      编辑
                    </Button>
                    <Button size="small" icon={<CopyOutlined />} onClick={() => openClone(p)}>
                      复制
                    </Button>
                    {p.status === "active" && (
                      <Button
                        size="small"
                        danger
                        icon={<StopOutlined />}
                        onClick={() => handleDisable(p)}
                      >
                        禁用
                      </Button>
                    )}
                  </div>
                </div>
                <div
                  style={{
                    fontSize: 11,
                    color: "var(--text-muted)",
                    marginTop: 6,
                  }}
                >
                  更新于 {display} · Prompt {p.prompt_version} · Schema {p.output_schema_version}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Create/Edit Drawer */}
      <Drawer
        title={editingId ? "编辑 Prompt 配置" : "新建 Prompt 配置"}
        width={480}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        destroyOnClose
        footer={
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <Button onClick={() => setDrawerOpen(false)}>取消</Button>
            <Button type="primary" loading={saving} onClick={handleSave}>
              {editingId ? "保存更新" : "创建配置"}
            </Button>
          </div>
        }
      >
        <div style={{ display: "grid", gap: 16 }}>
          <div>
            <label style={{ fontSize: 13, fontWeight: 500, display: "block", marginBottom: 4 }}>
              配置名称 *
            </label>
            <Input
              value={form.profile_name}
              onChange={(e) => setForm((f) => ({ ...f, profile_name: e.target.value }))}
              placeholder="例：元数据治理"
            />
          </div>
          <div>
            <label style={{ fontSize: 13, fontWeight: 500, display: "block", marginBottom: 4 }}>
              任务类型
            </label>
            <Select
              value={form.task_type}
              onChange={(v) => setForm((f) => ({ ...f, task_type: v }))}
              options={TASK_TYPES}
              style={{ width: "100%" }}
            />
          </div>
          <div>
            <label style={{ fontSize: 13, fontWeight: 500, display: "block", marginBottom: 4 }}>
              LiteLLM 模型别名
            </label>
            <Input
              value={form.litellm_model_alias}
              onChange={(e) => setForm((f) => ({ ...f, litellm_model_alias: e.target.value }))}
            />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div>
              <label style={{ fontSize: 13, fontWeight: 500, display: "block", marginBottom: 4 }}>
                Temperature
              </label>
              <InputNumber
                value={form.temperature}
                min={0}
                max={2}
                step={0.1}
                onChange={(v) => setForm((f) => ({ ...f, temperature: v ?? 0.3 }))}
                style={{ width: "100%" }}
              />
            </div>
            <div>
              <label style={{ fontSize: 13, fontWeight: 500, display: "block", marginBottom: 4 }}>
                Max Input Tokens
              </label>
              <InputNumber
                value={form.max_input_tokens}
                min={512}
                max={32768}
                step={512}
                onChange={(v) => setForm((f) => ({ ...f, max_input_tokens: v ?? 4096 }))}
                style={{ width: "100%" }}
              />
            </div>
          </div>
          <div>
            <label style={{ fontSize: 13, fontWeight: 500, display: "block", marginBottom: 4 }}>
              脱敏策略
            </label>
            <Select
              value={form.redaction_policy}
              onChange={(v) => setForm((f) => ({ ...f, redaction_policy: v }))}
              options={REDACTION_POLICIES}
              style={{ width: "100%" }}
            />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
            <div>
              <label style={{ fontSize: 13, fontWeight: 500, display: "block", marginBottom: 4 }}>
                Prompt 版本
              </label>
              <Input
                value={form.prompt_version}
                onChange={(e) => setForm((f) => ({ ...f, prompt_version: e.target.value }))}
              />
            </div>
            <div>
              <label style={{ fontSize: 13, fontWeight: 500, display: "block", marginBottom: 4 }}>
                Schema 版本
              </label>
              <Input
                value={form.output_schema_version}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    output_schema_version: e.target.value,
                  }))
                }
              />
            </div>
            <div>
              <label style={{ fontSize: 13, fontWeight: 500, display: "block", marginBottom: 4 }}>
                权重版本
              </label>
              <Input
                value={form.scoring_weight_version}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    scoring_weight_version: e.target.value,
                  }))
                }
              />
            </div>
          </div>
        </div>
      </Drawer>
    </>
  );
}
