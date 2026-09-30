"use client";

import { useCallback, useState } from "react";
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  message,
} from "antd";
import {
  DeleteOutlined,
  PauseOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
  StopOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";

import { deleteApiData, getApiData, postApiData } from "@/lib/api";
import type { QueryField, SyncPlan, SyncProvider, SyncRun } from "@/lib/data-sync";
import { formatTime } from "@/lib/format-time";

const frequencies = [
  { value: "1_month", label: "每月" },
  { value: "3_months", label: "每 3 个月" },
  { value: "6_months", label: "每 6 个月" },
  { value: "9_months", label: "每 9 个月" },
  { value: "1_year", label: "每年" },
];
const frequencyLabel = (value: string) =>
  frequencies.find((item) => item.value === value)?.label ?? value;
const time = (value: string | null) => (value ? formatTime(value).display : "-");
const activeRun = (run: SyncRun) => ["queued", "running", "paused"].includes(run.status);
const statusNames: Record<string, string> = {
  active: "运行中",
  paused: "已暂停",
  queued: "排队中",
  running: "同步中",
  succeeded: "成功",
  partially_succeeded: "部分成功",
  failed: "失败",
  cancelled: "已取消",
};
const statusColor: Record<string, string> = {
  active: "green",
  paused: "orange",
  queued: "blue",
  running: "processing",
  succeeded: "green",
  partially_succeeded: "orange",
  failed: "red",
  cancelled: "default",
};

function fieldType(field: QueryField): string | null {
  if (field.type) return field.type;
  const variants = field.anyOf?.filter((item) => item.type !== "null") ?? [];
  return variants.length === 1 ? (variants[0].type ?? null) : null;
}

function ProviderLogo({ name, code }: { name: string; code: string }) {
  const colors = ["#137c72", "#bf6a30", "#4f66ae", "#9b4e70"];
  const hash = Array.from(code).reduce((sum, char) => sum + char.charCodeAt(0), 0);
  return (
    <svg width="42" height="42" viewBox="0 0 42 42" role="img" aria-label={`${name} 标识`}>
      <rect width="42" height="42" rx="7" fill={colors[hash % colors.length]} />
      <path
        d="M11 29V13h9c6 0 11 4 11 8s-5 8-11 8h-9zm5-4h4c4 0 6-2 6-4s-2-4-6-4h-4v8z"
        fill="white"
      />
    </svg>
  );
}

function QueryInput({ field }: { field: QueryField }) {
  const type = fieldType(field);
  if (field.enum)
    return <Select options={field.enum.map((value) => ({ label: String(value), value }))} />;
  if (type === "string") return <Input maxLength={field.maxLength} />;
  if (type === "integer" || type === "number")
    return (
      <InputNumber
        className="w-full"
        min={field.minimum}
        max={field.maximum}
        precision={type === "integer" ? 0 : undefined}
      />
    );
  if (type === "boolean")
    return (
      <Select
        options={[
          { label: "是", value: true },
          { label: "否", value: false },
        ]}
      />
    );
  return <Alert type="warning" title="此参数类型暂不支持表单输入" />;
}

export function DataSyncContent({
  initialProviders,
  initialPlans,
  initialRuns,
  initialError,
}: {
  initialProviders: SyncProvider[];
  initialPlans: SyncPlan[];
  initialRuns: SyncRun[];
  initialError: string | null;
}) {
  const [providers, setProviders] = useState(initialProviders);
  const [plans, setPlans] = useState(initialPlans);
  const [runs, setRuns] = useState(initialRuns);
  const [runPage, setRunPage] = useState(1);
  const [error, setError] = useState(initialError);
  const [busy, setBusy] = useState<string | null>(null);
  const [selectedProvider, setSelectedProvider] = useState<SyncProvider | null>(null);
  const [selectedPlan, setSelectedPlan] = useState<SyncPlan | null>(null);
  const [form] = Form.useForm();

  const refresh = useCallback(
    async (page = runPage) => {
      const [providerResult, planResult, runResult] = await Promise.all([
        getApiData<SyncProvider[]>("/api/data-sync/providers", []),
        getApiData<SyncPlan[]>("/api/data-sync/plans", []),
        getApiData<SyncRun[]>("/api/data-sync/runs", [], { page: String(page), pageSize: "100" }),
      ]);
      if (!providerResult.ok || !planResult.ok || !runResult.ok) {
        setError(providerResult.error ?? planResult.error ?? runResult.error);
        return;
      }
      setProviders(providerResult.data);
      setPlans(planResult.data);
      setRuns(runResult.data);
      setRunPage(page);
      setError(null);
    },
    [runPage],
  );

  async function act(key: string, action: () => Promise<unknown>): Promise<boolean> {
    setBusy(key);
    try {
      await action();
      message.success("操作成功");
      await refresh(key === "create" ? 1 : runPage);
      return true;
    } catch (cause) {
      const detail = cause instanceof Error ? cause.message : "操作失败";
      message.error(detail);
      setError(detail);
      return false;
    } finally {
      setBusy(null);
    }
  }

  function openCreate(provider: SyncProvider) {
    form.resetFields();
    const defaults = Object.fromEntries(
      Object.entries(provider.query_schema.properties ?? {})
        .filter(([, field]) => field.default !== undefined)
        .map(([name, field]) => [name, field.default]),
    );
    form.setFieldsValue({ frequency: "1_month", query_config: defaults });
    setSelectedProvider(provider);
  }

  async function createPlan(values: {
    name: string;
    frequency: string;
    query_config?: Record<string, unknown>;
  }) {
    if (!selectedProvider) return;
    const providerCode = selectedProvider.provider_code;
    const created = await act("create", () =>
      postApiData("/api/data-sync/plans", {
        name: values.name.trim(),
        provider_code: providerCode,
        frequency: values.frequency,
        query_config: values.query_config ?? {},
      }),
    );
    if (created) setSelectedProvider(null);
  }

  const required = selectedProvider?.query_schema.required ?? [];
  const fields = Object.entries(selectedProvider?.query_schema.properties ?? {});
  const unsupported = fields.some(
    ([, field]) =>
      !field.enum && !["string", "integer", "number", "boolean"].includes(fieldType(field) ?? ""),
  );

  return (
    <div className="space-y-6 pb-8">
      {error && (
        <Alert
          type="error"
          showIcon
          title="数据同步操作失败"
          description={error}
          action={
            <Button size="small" onClick={() => refresh()}>
              重试
            </Button>
          }
        />
      )}
      <section aria-label="Provider">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-base font-semibold">Provider</h2>
          <Tooltip title="刷新数据">
            <Button icon={<ReloadOutlined />} aria-label="刷新数据" onClick={() => refresh()} />
          </Tooltip>
        </div>
        {providers.length === 0 ? (
          <Empty description="暂无可用 Provider" />
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {providers.map((provider) => (
              <div
                key={provider.provider_code}
                className="border-line bg-surface rounded-md border p-4"
              >
                <div className="mb-4 flex items-center gap-3">
                  <ProviderLogo name={provider.display_name} code={provider.provider_code} />
                  <div className="min-w-0">
                    <div className="truncate font-semibold">{provider.display_name}</div>
                    <div className="text-text-secondary truncate text-xs">
                      {provider.provider_code}
                    </div>
                  </div>
                  <Tag
                    className="ml-auto"
                    color={provider.status === "enabled" ? "green" : "default"}
                  >
                    {provider.status === "enabled" ? "可用" : "停用"}
                  </Tag>
                </div>
                <Descriptions
                  size="small"
                  column={1}
                  items={[
                    { key: "server", label: "API Server", children: provider.api_server_url },
                    { key: "tenant", label: "租户", children: provider.tenant_name },
                    {
                      key: "credential",
                      label: "凭证",
                      children:
                        provider.credential_status === "available"
                          ? "已配置"
                          : provider.credential_status,
                    },
                    { key: "version", label: "Adapter", children: provider.adapter_version },
                  ]}
                />
                <Button
                  type="primary"
                  icon={<PlusOutlined />}
                  disabled={provider.status !== "enabled"}
                  onClick={() => openCreate(provider)}
                >
                  新建同步计划
                </Button>
              </div>
            ))}
          </div>
        )}
      </section>

      <section aria-label="同步计划">
        <h2 className="mb-3 text-base font-semibold">
          同步计划 <span className="text-text-secondary text-sm font-normal">{plans.length}</span>
        </h2>
        <Table
          rowKey="id"
          size="small"
          dataSource={plans}
          scroll={{ x: 900 }}
          pagination={{ pageSize: 10 }}
          locale={{ emptyText: "暂无同步计划" }}
          columns={[
            {
              title: "计划",
              dataIndex: "name",
              key: "name",
              render: (value: string, plan: SyncPlan) => (
                <div>
                  <div className="font-medium">{value}</div>
                  <div className="text-text-secondary text-xs">{plan.provider_code}</div>
                </div>
              ),
            },
            { title: "频率", dataIndex: "frequency", key: "frequency", render: frequencyLabel },
            {
              title: "查询参数",
              dataIndex: "query_config",
              key: "query",
              render: (value: Record<string, unknown>) => (
                <Tooltip
                  title={
                    <pre className="max-w-sm whitespace-pre-wrap">
                      {JSON.stringify(value, null, 2)}
                    </pre>
                  }
                >
                  <span className="inline-block max-w-48 truncate align-middle">
                    {JSON.stringify(value)}
                  </span>
                </Tooltip>
              ),
            },
            {
              title: "计划状态",
              dataIndex: "status",
              key: "status",
              render: (value: string) => (
                <Tag color={statusColor[value]}>{statusNames[value] ?? value}</Tag>
              ),
            },
            { title: "上次运行", dataIndex: "last_run_at", key: "last", render: time },
            { title: "下次运行", dataIndex: "next_run_at", key: "next", render: time },
            {
              title: "操作",
              key: "action",
              render: (_: unknown, plan: SyncPlan) => (
                <Space size={4}>
                  <Tooltip title="查看运行记录">
                    <Button
                      aria-label={`查看计划 ${plan.name} 的运行记录`}
                      icon={<UnorderedListOutlined />}
                      onClick={() => setSelectedPlan(plan)}
                    />
                  </Tooltip>
                  <Tooltip title="手动创建运行">
                    <Button
                      aria-label={`运行 ${plan.name}`}
                      icon={<PlayCircleOutlined />}
                      disabled={
                        plan.status !== "active" ||
                        runs.some((run) => run.data_sync_config_id === plan.id && activeRun(run))
                      }
                      loading={busy === `run-${plan.id}`}
                      onClick={() =>
                        act(`run-${plan.id}`, () =>
                          postApiData(`/api/data-sync/plans/${plan.id}/runs`, {}),
                        )
                      }
                    />
                  </Tooltip>
                  <Tooltip title={plan.status === "active" ? "暂停计划" : "恢复计划"}>
                    <Button
                      aria-label={`${plan.status === "active" ? "暂停" : "恢复"}计划 ${plan.name}`}
                      icon={plan.status === "active" ? <PauseOutlined /> : <PlayCircleOutlined />}
                      loading={busy === `plan-${plan.id}`}
                      onClick={() =>
                        act(`plan-${plan.id}`, () =>
                          postApiData(
                            `/api/data-sync/plans/${plan.id}/${plan.status === "active" ? "pause" : "resume"}`,
                            {},
                          ),
                        )
                      }
                    />
                  </Tooltip>
                  <Popconfirm
                    title="删除此同步计划？"
                    description="历史运行记录会保留。运行未结束时无法删除。"
                    onConfirm={() =>
                      act(`delete-${plan.id}`, () =>
                        deleteApiData(`/api/data-sync/plans/${plan.id}`),
                      )
                    }
                  >
                    <Tooltip title="删除计划">
                      <Button
                        aria-label={`删除计划 ${plan.name}`}
                        danger
                        icon={<DeleteOutlined />}
                        loading={busy === `delete-${plan.id}`}
                      />
                    </Tooltip>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </section>

      <Drawer
        title={`新建同步计划${selectedProvider ? ` · ${selectedProvider.display_name}` : ""}`}
        open={!!selectedProvider}
        onClose={() => setSelectedProvider(null)}
        width={520}
        extra={
          <Button
            type="primary"
            disabled={unsupported}
            loading={busy === "create"}
            onClick={() => form.submit()}
          >
            创建计划
          </Button>
        }
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={createPlan}>
          <Form.Item
            name="name"
            label="计划名称"
            rules={[{ required: true, whitespace: true, message: "请输入计划名称" }, { max: 128 }]}
          >
            <Input maxLength={128} />
          </Form.Item>
          <Form.Item name="frequency" label="同步频率" rules={[{ required: true }]}>
            <Select options={frequencies} />
          </Form.Item>
          {fields.map(([name, field]) => (
            <Form.Item
              key={name}
              name={["query_config", name]}
              label={field.title ?? name}
              extra={field.description}
              rules={[
                { required: required.includes(name), message: `请填写${field.title ?? name}` },
                ...(field.minLength ? [{ min: field.minLength }] : []),
              ]}
            >
              <QueryInput field={field} />
            </Form.Item>
          ))}
          {unsupported && (
            <Alert
              type="warning"
              showIcon
              title="此 Provider 的查询参数包含暂不支持的类型，无法创建计划"
            />
          )}
        </Form>
      </Drawer>

      <Drawer
        title={`运行记录${selectedPlan ? ` · ${selectedPlan.name}` : ""}`}
        open={!!selectedPlan}
        onClose={() => setSelectedPlan(null)}
        width={900}
        extra={
          <Button icon={<ReloadOutlined />} onClick={() => refresh()}>
            刷新
          </Button>
        }
      >
        <Table
          rowKey="id"
          size="small"
          dataSource={runs.filter((run) => run.data_sync_config_id === selectedPlan?.id)}
          scroll={{ x: 1050 }}
          pagination={{ pageSize: 10 }}
          locale={{ emptyText: "暂无同步运行" }}
          columns={[
            {
              title: "运行 / Provider",
              key: "id",
              render: (_: unknown, run: SyncRun) => (
                <div>
                  <span className="font-mono text-xs" title={run.id}>
                    {run.id.slice(0, 8)}
                  </span>
                  <div className="text-text-secondary text-xs">{run.provider_code}</div>
                </div>
              ),
            },
            {
              title: "运行状态",
              dataIndex: "status",
              key: "status",
              render: (value: string) => (
                <Tag color={statusColor[value]}>{statusNames[value] ?? value}</Tag>
              ),
            },
            {
              title: "外部任务 ID",
              dataIndex: "external_task_id",
              key: "external",
              render: (value: string | null) => (
                <span className="font-mono text-xs" title={value ?? undefined}>
                  {value ?? "-"}
                </span>
              ),
            },
            {
              title: "处理 / 成功 / 失败 / 跳过",
              key: "counts",
              render: (_: unknown, run: SyncRun) =>
                `${run.processed_count} / ${run.success_count} / ${run.failure_count} / ${run.skipped_count}`,
            },
            {
              title: "失败摘要",
              dataIndex: "failure_summary",
              key: "failure",
              render: (value: string | null) =>
                value ? (
                  <Tooltip title={value}>
                    <span className="inline-block max-w-48 truncate align-middle text-red-600">
                      {value}
                    </span>
                  </Tooltip>
                ) : (
                  "-"
                ),
            },
            { title: "更新时间", dataIndex: "updated_at", key: "updated", render: time },
            {
              title: "操作",
              key: "action",
              render: (_: unknown, run: SyncRun) => (
                <Space size={4}>
                  {run.status === "running" && (
                    <Tooltip title="暂停本次运行">
                      <Button
                        aria-label={`暂停运行 ${run.id}`}
                        icon={<PauseOutlined />}
                        loading={busy === `control-${run.id}`}
                        onClick={() =>
                          act(`control-${run.id}`, () =>
                            postApiData(`/api/data-sync/runs/${run.id}/pause`, {}),
                          )
                        }
                      />
                    </Tooltip>
                  )}
                  {run.status === "paused" && (
                    <Tooltip title="恢复本次运行">
                      <Button
                        aria-label={`恢复运行 ${run.id}`}
                        icon={<PlayCircleOutlined />}
                        loading={busy === `control-${run.id}`}
                        onClick={() =>
                          act(`control-${run.id}`, () =>
                            postApiData(`/api/data-sync/runs/${run.id}/resume`, {}),
                          )
                        }
                      />
                    </Tooltip>
                  )}
                  {activeRun(run) && (
                    <Popconfirm
                      title="取消本次运行？"
                      onConfirm={() =>
                        act(`control-${run.id}`, () =>
                          postApiData(`/api/data-sync/runs/${run.id}/cancel`, {}),
                        )
                      }
                    >
                      <Tooltip title="取消本次运行">
                        <Button
                          aria-label={`取消运行 ${run.id}`}
                          danger
                          icon={<StopOutlined />}
                          loading={busy === `control-${run.id}`}
                        />
                      </Tooltip>
                    </Popconfirm>
                  )}
                </Space>
              ),
            },
          ]}
        />
      </Drawer>
    </div>
  );
}
