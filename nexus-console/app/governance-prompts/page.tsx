"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Skeleton,
  Space,
  Table,
} from "antd";
import { PageHeader } from "@/components/PageHeader";
import { StatusLabel } from "@/components/StatusLabel";
import {
  fetchPromptTemplates,
  updatePromptTemplate,
  disablePromptTemplate,
  type PromptTemplateSummary,
  type UpdatePromptTemplatePayload,
} from "@/lib/governance-prompts-api";

const TASK_TYPE_LABELS: Record<string, string> = {
  classification: "分类",
  level_assessment: "分级评估",
  tagging: "标签",
  quality_scoring: "质量评分",
  knowledge_type_inference: "知识类型推断",
};

export default function GovernancePromptsPage() {
  const { message } = App.useApp();
  const [templates, setTemplates] = useState<PromptTemplateSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Edit modal
  const [editOpen, setEditOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<PromptTemplateSummary | null>(null);
  const [saving, setSaving] = useState(false);
  const [editForm] = Form.useForm();

  const loadTemplates = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    const result = await fetchPromptTemplates();
    if (result.ok) {
      setTemplates(result.templates);
    } else {
      setLoadError(`无法加载 Prompt 模板：${result.error}`);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  function openEdit(record: PromptTemplateSummary) {
    setEditingTemplate(record);
    editForm.setFieldsValue({
      template_name: record.template_name,
      litellm_model_alias: record.litellm_model_alias,
      temperature: record.temperature,
      max_input_tokens: record.max_input_tokens,
      change_summary: "",
    });
    setEditOpen(true);
  }

  async function handleEditSubmit() {
    if (!editingTemplate) return;
    try {
      const values = await editForm.validateFields();
      setSaving(true);
      const payload: UpdatePromptTemplatePayload = {
        template_name: values.template_name,
        litellm_model_alias: values.litellm_model_alias || null,
        temperature: values.temperature ?? null,
        max_input_tokens: values.max_input_tokens ?? null,
        change_summary: values.change_summary || "Console update",
      };
      const result = await updatePromptTemplate(editingTemplate.task_type, payload);
      setSaving(false);
      if (result.ok) {
        message.success(
          `Prompt 模板已更新 — 新版本 v${result.template.template_version}`,
        );
        setEditOpen(false);
        loadTemplates();
      } else {
        message.error(result.error);
      }
    } catch {
      // Form validation failed — Antd shows field errors
      setSaving(false);
    }
  }

  async function handleDisable(record: PromptTemplateSummary) {
    Modal.confirm({
      title: `禁用 Prompt 模板`,
      content: `确定要禁用 "${record.template_name}" (v${record.template_version}) 吗？`,
      okText: "禁用",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        const result = await disablePromptTemplate(record.id);
        if (result.ok) {
          message.success(`已禁用 ${record.template_name}`);
          loadTemplates();
        } else {
          message.error(result.error);
        }
      },
    });
  }

  const columns = [
    {
      title: "任务类型",
      dataIndex: "task_type",
      key: "task_type",
      width: 160,
      render: (v: string) => TASK_TYPE_LABELS[v] ?? v,
    },
    { title: "模板名称", dataIndex: "template_name", key: "template_name", ellipsis: true },
    { title: "版本", dataIndex: "template_version", key: "template_version", width: 70 },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 90,
      render: (s: string) => <StatusLabel value={s} />,
    },
    {
      title: "模型别名",
      dataIndex: "litellm_model_alias",
      key: "litellm_model_alias",
      width: 140,
      ellipsis: true,
    },
    {
      title: "温度",
      dataIndex: "temperature",
      key: "temperature",
      width: 70,
      render: (v: number | null) => v ?? "-",
    },
    {
      title: "变更摘要",
      dataIndex: "change_summary",
      key: "change_summary",
      ellipsis: true,
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 170,
    },
    {
      title: "操作",
      key: "actions",
      width: 160,
      render: (_: unknown, record: PromptTemplateSummary) => (
        <Space size="small">
          <Button type="link" size="small" onClick={() => openEdit(record)}>
            编辑
          </Button>
          {record.status === "active" && (
            <Button
              type="link"
              size="small"
              danger
              onClick={() => handleDisable(record)}
            >
              禁用
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        eyebrow="资产与治理 — Prompt 模板"
        title="AI Prompt 配置"
        description="管理治理流水线各阶段的 Prompt 模板。编辑模板会创建新版本并将旧版本归档，修改立即生效。"
      />

      {loadError && (
        <Alert type="error" showIcon className="mb-4" title={loadError} />
      )}

      <Alert
        className="mb-4"
        type="info"
        showIcon
        title="每个任务类型同时只有一个 active 版本。编辑模板将自动创建新版本并归档旧版本。Prompt 模板支持 {{RULES}} 和 {{DOCUMENT}} 占位符。"
      />

      {loading ? (
        <Card>
          <Skeleton active paragraph={{ rows: 6 }} />
        </Card>
      ) : (
        <Table
          columns={columns}
          dataSource={templates}
          rowKey="id"
          pagination={false}
          size="middle"
        />
      )}

      {/* Edit modal */}
      <Modal
        title={
          editingTemplate
            ? `编辑 Prompt — ${TASK_TYPE_LABELS[editingTemplate.task_type] ?? editingTemplate.task_type}`
            : "编辑 Prompt"
        }
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={handleEditSubmit}
        confirmLoading={saving}
        okText="保存为新版本"
        width={640}
        destroyOnClose
      >
        {editingTemplate && (
          <Form form={editForm} layout="vertical" className="mt-4">
            <Form.Item
              name="template_name"
              label="模板名称"
              rules={[{ required: true, message: "请输入模板名称" }]}
            >
              <Input />
            </Form.Item>
            <Form.Item name="litellm_model_alias" label="LiteLLM 模型别名">
              <Input placeholder="如 gpt-4o、claude-sonnet-4-6" />
            </Form.Item>
            <Space size="middle">
              <Form.Item name="temperature" label="Temperature">
                <InputNumber min={0} max={2} step={0.1} />
              </Form.Item>
              <Form.Item name="max_input_tokens" label="最大输入 Token">
                <InputNumber min={100} max={128000} step={100} />
              </Form.Item>
            </Space>
            <Form.Item
              name="change_summary"
              label="变更摘要"
              rules={[{ required: true, message: "请输入变更摘要" }]}
            >
              <Input.TextArea rows={2} placeholder="描述本次变更内容" />
            </Form.Item>
          </Form>
        )}
      </Modal>
    </>
  );
}
