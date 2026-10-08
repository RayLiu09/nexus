"use client";

import { useRef, useState } from "react";
import {
  Alert,
  App,
  Button,
  Checkbox,
  DatePicker,
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
import type { QueryField, SyncPlan, SyncProvider, SyncRun, SyncRunLogs } from "@/lib/data-sync";
import { formatTime } from "@/lib/format-time";
import dayjs from "dayjs";

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
type RunFilters = { run_id?: string; status?: string; created_from?: string; created_to?: string };
const RUN_PAGE_SIZE = 20;
const AUDIT_PAGE_SIZE = 10;
const runStatuses = [
  "queued",
  "running",
  "paused",
  "succeeded",
  "partially_succeeded",
  "failed",
  "cancelled",
];
const auditNames: Record<string, string> = {
  DataSyncRunQueued: "运行已创建",
  DataSyncRunStatusChanged: "运行状态变更",
  DataSyncRunControlled: "运行控制",
};
const controlNames: Record<string, string> = { pause: "暂停", resume: "恢复", cancel: "取消" };
const statusNames: Record<string, string> = {
  active: "运行中",
  deleted: "已删除",
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
  initialError,
}: {
  initialProviders: SyncProvider[];
  initialPlans: SyncPlan[];
  initialError: string | null;
}) {
  const [providers, setProviders] = useState(initialProviders);
  const [plans, setPlans] = useState(initialPlans);
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [runTotal, setRunTotal] = useState(0);
  const [runLoading, setRunLoading] = useState(false);
  const [runPage, setRunPage] = useState(1);
  const [showDeleted, setShowDeleted] = useState(false);
  const [providerFilter, setProviderFilter] = useState<string | undefined>();
  const [runIdInput, setRunIdInput] = useState("");
  const [runStatusInput, setRunStatusInput] = useState<string | undefined>();
  const [timeRange, setTimeRange] = useState<[string, string] | null>(null);
  const [appliedFilters, setAppliedFilters] = useState<RunFilters>({});
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [runLogs, setRunLogs] = useState<SyncRunLogs | null>(null);
  const [auditPage, setAuditPage] = useState(1);
  const [logsLoading, setLogsLoading] = useState(false);
  const [error, setError] = useState(initialError);
  const [busy, setBusy] = useState<string | null>(null);
  const [selectedProvider, setSelectedProvider] = useState<SyncProvider | null>(null);
  const [selectedPlan, setSelectedPlan] = useState<SyncPlan | null>(null);
  const runRequestSeq = useRef(0);
  const logRequestSeq = useRef(0);
  const { message } = App.useApp();
  const [form] = Form.useForm();

  async function loadRuns(plan: SyncPlan, page: number, filters: RunFilters) {
    const requestSeq = ++runRequestSeq.current;
    setRunLoading(true);
    const result = await getApiData<SyncRun[]>("/api/data-sync/runs", [], {
      plan_id: plan.id,
      provider_code: plan.provider_code,
      page: String(page),
      pageSize: String(RUN_PAGE_SIZE),
      ...filters,
    });
    if (requestSeq !== runRequestSeq.current) return;
    setRunLoading(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    setRuns(result.data);
    setRunTotal(result.total ?? result.data.length);
    setRunPage(page);
    setError(null);
  }

  async function loadLogs(runId: string, page: number) {
    const requestSeq = ++logRequestSeq.current;
    setLogsLoading(true);
    const result = await getApiData<SyncRunLogs | null>(
      `/api/data-sync/runs/${encodeURIComponent(runId)}/logs`,
      null,
      { page: String(page), pageSize: String(AUDIT_PAGE_SIZE) },
    );
    if (requestSeq !== logRequestSeq.current) return;
    setLogsLoading(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    setRunLogs(result.data);
    setAuditPage(page);
    setError(null);
  }

  async function refresh() {
    const [providerResult, planResult] = await Promise.all([
      getApiData<SyncProvider[]>("/api/data-sync/providers", []),
      getApiData<SyncPlan[]>("/api/data-sync/plans", [], { include_deleted: String(showDeleted) }),
    ]);
    if (!providerResult.ok || !planResult.ok) {
      setError(providerResult.error ?? planResult.error);
      return;
    }
    setProviders(providerResult.data);
    setPlans(planResult.data);
    setError(null);
    if (selectedPlan) await loadRuns(selectedPlan, runPage, appliedFilters);
    if (selectedRunId) await loadLogs(selectedRunId, auditPage);
  }

  async function toggleDeleted(checked: boolean) {
    setShowDeleted(checked);
    const result = await getApiData<SyncPlan[]>("/api/data-sync/plans", [], {
      include_deleted: String(checked),
    });
    if (result.ok) {
      setPlans(result.data);
      setError(null);
    } else {
      setError(result.error);
    }
  }

  async function act(key: string, action: () => Promise<unknown>): Promise<boolean> {
    setBusy(key);
    try {
      await action();
      message.success("操作成功");
      await refresh();
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

  function openRunHistory(plan: SyncPlan) {
    setSelectedPlan(plan);
    setRunIdInput("");
    setRunStatusInput(undefined);
    setTimeRange(null);
    setAppliedFilters({});
    setRuns([]);
    setRunTotal(0);
    void loadRuns(plan, 1, {});
  }

  function searchRuns() {
    if (!selectedPlan) return;
    const filters: RunFilters = {
      ...(runIdInput.trim() ? { run_id: runIdInput.trim() } : {}),
      ...(runStatusInput ? { status: runStatusInput } : {}),
      ...(timeRange ? { created_from: timeRange[0], created_to: timeRange[1] } : {}),
    };
    setAppliedFilters(filters);
    void loadRuns(selectedPlan, 1, filters);
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
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold">
            同步计划 <span className="text-text-secondary text-sm font-normal">{plans.length}</span>
          </h2>
          <Space wrap>
            <Select
              className="min-w-36"
              aria-label="按 Provider 筛选计划"
              placeholder="全部 Provider"
              allowClear
              value={providerFilter}
              onChange={setProviderFilter}
              options={providers.map((provider) => ({
                value: provider.provider_code,
                label: provider.display_name,
              }))}
            />
            <Checkbox
              checked={showDeleted}
              onChange={(event) => void toggleDeleted(event.target.checked)}
            >
              包含已删除计划
            </Checkbox>
          </Space>
        </div>
        <Table
          rowKey="id"
          size="small"
          dataSource={plans.filter(
            (plan) => !providerFilter || plan.provider_code === providerFilter,
          )}
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
                      onClick={() => openRunHistory(plan)}
                    />
                  </Tooltip>
                  <Tooltip title="手动创建运行">
                    <Button
                      aria-label={`运行 ${plan.name}`}
                      icon={<PlayCircleOutlined />}
                      disabled={plan.status !== "active"}
                      loading={busy === `run-${plan.id}`}
                      onClick={() =>
                        act(`run-${plan.id}`, () =>
                          postApiData(`/api/data-sync/plans/${plan.id}/runs`, {}),
                        )
                      }
                    />
                  </Tooltip>
                  {plan.status !== "deleted" && (
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
                  )}
                  {plan.status !== "deleted" && (
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
                  )}
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
        onClose={() => {
          runRequestSeq.current += 1;
          logRequestSeq.current += 1;
          setSelectedPlan(null);
          setSelectedRunId(null);
          setRunLogs(null);
        }}
        width={960}
        extra={
          <Button
            icon={<ReloadOutlined />}
            loading={runLoading}
            onClick={() => selectedPlan && loadRuns(selectedPlan, runPage, appliedFilters)}
          >
            刷新
          </Button>
        }
      >
        <div className="mb-4 flex flex-wrap items-end gap-3">
          <div className="min-w-48 flex-1">
            <label htmlFor="sync-run-id" className="text-text-secondary mb-1 block text-xs">
              运行 ID
            </label>
            <Input
              id="sync-run-id"
              placeholder="精确查找运行 ID"
              value={runIdInput}
              onChange={(event) => setRunIdInput(event.target.value)}
              onPressEnter={searchRuns}
            />
          </div>
          <div className="w-40">
            <label htmlFor="sync-run-status" className="text-text-secondary mb-1 block text-xs">
              状态
            </label>
            <Select
              id="sync-run-status"
              className="w-full"
              placeholder="全部状态"
              allowClear
              value={runStatusInput}
              onChange={setRunStatusInput}
              options={runStatuses.map((value) => ({ value, label: statusNames[value] }))}
            />
          </div>
          <div>
            <span className="text-text-secondary mb-1 block text-xs">创建时间</span>
            <DatePicker.RangePicker
              value={timeRange ? [dayjs(timeRange[0]), dayjs(timeRange[1])] : null}
              onChange={(dates) =>
                setTimeRange(
                  dates?.[0] && dates?.[1]
                    ? [dates[0].startOf("day").toISOString(), dates[1].endOf("day").toISOString()]
                    : null,
                )
              }
            />
          </div>
          <Button type="primary" onClick={searchRuns}>
            查询
          </Button>
        </div>
        <div className="text-text-secondary mb-3 text-xs">
          Provider：{selectedPlan?.provider_code ?? "-"} · 共 {runTotal} 次运行
        </div>
        <Table
          rowKey="id"
          size="small"
          loading={runLoading}
          dataSource={runs}
          scroll={{ x: 1050 }}
          pagination={{
            current: runPage,
            pageSize: RUN_PAGE_SIZE,
            total: runTotal,
            showSizeChanger: false,
            onChange: (page) => selectedPlan && loadRuns(selectedPlan, page, appliedFilters),
          }}
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
                  <Tooltip title="查看日志和审计">
                    <Button
                      aria-label={`查看运行 ${run.id} 日志`}
                      icon={<UnorderedListOutlined />}
                      onClick={() => {
                        setSelectedRunId(run.id);
                        setRunLogs(null);
                        void loadLogs(run.id, 1);
                      }}
                    />
                  </Tooltip>
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
      <Drawer
        title="运行日志与审计"
        open={!!selectedRunId}
        onClose={() => {
          logRequestSeq.current += 1;
          setSelectedRunId(null);
          setRunLogs(null);
        }}
        width={620}
        loading={logsLoading && !runLogs}
        extra={
          <Button
            icon={<ReloadOutlined />}
            onClick={() => selectedRunId && loadLogs(selectedRunId, auditPage)}
          >
            刷新
          </Button>
        }
      >
        {runLogs && (
          <div className="space-y-5">
            <Descriptions
              size="small"
              column={1}
              items={[
                {
                  key: "id",
                  label: "运行 ID",
                  children: <code className="text-xs break-all">{runLogs.run_id}</code>,
                },
                { key: "provider", label: "Provider", children: runLogs.provider_code },
                {
                  key: "status",
                  label: "状态",
                  children: (
                    <Tag color={statusColor[runLogs.status]}>
                      {statusNames[runLogs.status] ?? runLogs.status}
                    </Tag>
                  ),
                },
                { key: "version", label: "Adapter 版本", children: runLogs.adapter_version },
                {
                  key: "query",
                  label: "查询快照摘要",
                  children: <code className="text-xs break-all">{runLogs.query_summary}</code>,
                },
                {
                  key: "hash",
                  label: "查询 hash",
                  children: <code className="text-xs break-all">{runLogs.query_hash}</code>,
                },
                {
                  key: "external",
                  label: "外部任务 ID",
                  children: runLogs.external_task_id ? (
                    <code className="text-xs break-all">{runLogs.external_task_id}</code>
                  ) : (
                    "-"
                  ),
                },
                {
                  key: "counts",
                  label: "处理 / 成功 / 失败 / 跳过",
                  children: `${runLogs.processed_count} / ${runLogs.success_count} / ${runLogs.failure_count} / ${runLogs.skipped_count}`,
                },
                { key: "failure", label: "失败摘要", children: runLogs.failure_summary ?? "-" },
                {
                  key: "control",
                  label: "最近控制",
                  children: runLogs.last_control_action
                    ? `${controlNames[runLogs.last_control_action] ?? runLogs.last_control_action} · ${time(runLogs.last_control_requested_at)} · ${runLogs.last_control_operator_id ?? "-"}`
                    : "-",
                },
              ]}
            />
            <div>
              <h3 className="mb-2 text-sm font-semibold">
                审计记录{" "}
                <span className="text-text-secondary font-normal">{runLogs.audit_total}</span>
              </h3>
              <Table
                size="small"
                rowKey="id"
                dataSource={runLogs.audit_events}
                scroll={{ x: 720 }}
                pagination={{
                  current: auditPage,
                  pageSize: AUDIT_PAGE_SIZE,
                  total: runLogs.audit_total,
                  showSizeChanger: false,
                  onChange: (page) => selectedRunId && loadLogs(selectedRunId, page),
                }}
                columns={[
                  { title: "时间", dataIndex: "created_at", key: "time", width: 110, render: time },
                  {
                    title: "事件",
                    dataIndex: "event_type",
                    key: "event",
                    width: 125,
                    render: (value: string) => auditNames[value] ?? value,
                  },
                  {
                    title: "操作人",
                    key: "actor",
                    width: 110,
                    render: (_: unknown, event) => event.actor_id ?? event.actor_type ?? "-",
                  },
                  {
                    title: "Trace ID",
                    dataIndex: "trace_id",
                    key: "trace",
                    width: 150,
                    render: (value: string | null) =>
                      value ? <code className="text-xs break-all">{value}</code> : "-",
                  },
                  {
                    title: "摘要",
                    dataIndex: "summary",
                    key: "summary",
                    render: (value: Record<string, string>) => (
                      <span className="text-xs break-all">{JSON.stringify(value)}</span>
                    ),
                  },
                ]}
              />
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}
