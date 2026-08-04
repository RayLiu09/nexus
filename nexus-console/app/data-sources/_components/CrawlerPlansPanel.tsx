"use client";

import { useEffect, useState } from "react";
import {
  Alert,
  App,
  Button,
  Descriptions,
  Drawer,
  Form,
  Input,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import {
  CloudDownloadOutlined,
  DeleteOutlined,
  HistoryOutlined,
  LinkOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
} from "@ant-design/icons";

import { StatusLabel } from "@/components/StatusLabel";
import { formatTime } from "@/lib/format-time";
import { createIdempotencyKey } from "@/lib/idempotency";
import type {
  CrawlerConfig,
  CrawlerPlan,
  CrawlerRegion,
  CrawlerRun,
  CrawlerSites,
  CrawlerTargetSite,
} from "@/lib/api";

type ApiProxyResult<T> =
  | { ok: true; data: T; total: number | null; traceId: string | null }
  | { ok: false; status: number; message: string };

type PlanFormState = {
  mode: "quick_start" | "custom";
  name: string;
  dataSourceId: string;
  regionCode: string;
  executionMode: "run_once" | "scheduled";
  scheduleCron: string;
  topicKeywords: string;
  targetUrls: string;
};

type CrawlerRunSummaryItem = {
  url: string;
  title?: string | null;
  description?: string | null;
  reason?: string | null;
  source_url?: string | null;
  content_hash?: string | null;
  content_chars?: number | null;
  raw_representation?: string | null;
  duplicate?: boolean | null;
  raw_object_id?: string | null;
  pipeline_type?: string | null;
};

const INITIAL_FORM: PlanFormState = {
  mode: "quick_start",
  name: "",
  dataSourceId: "",
  regionCode: "national",
  executionMode: "run_once",
  scheduleCron: "",
  topicKeywords: "",
  targetUrls: "",
};

const BUILTIN_FIRECRAWL_SOURCE_ID = "__builtin_firecrawl__";

async function crawlerGet<T>(path: string): Promise<ApiProxyResult<T>> {
  const response = await fetch(`/api/crawler${path}`, { cache: "no-store" });
  return response.json();
}

async function crawlerPost<T>(path: string, body: unknown): Promise<ApiProxyResult<T>> {
  const response = await fetch(`/api/crawler${path}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "Idempotency-Key": createIdempotencyKey(),
    },
    body: JSON.stringify(body ?? {}),
  });
  return response.json();
}

function splitLines(value: string): string[] {
  return value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function numberFrom(summary: Record<string, unknown>, key: string): number {
  const value = summary[key];
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function objectArrayFrom(summary: Record<string, unknown>, key: string): CrawlerRunSummaryItem[] {
  const value = summary[key];
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((item) => ({
      url: String(item.url || item.source_url || ""),
      title: typeof item.title === "string" ? item.title : null,
      description: typeof item.description === "string" ? item.description : null,
      reason: typeof item.reason === "string" ? item.reason : null,
      source_url: typeof item.source_url === "string" ? item.source_url : null,
      content_hash: typeof item.content_hash === "string" ? item.content_hash : null,
      content_chars: typeof item.content_chars === "number" ? item.content_chars : null,
      raw_representation:
        typeof item.raw_representation === "string" ? item.raw_representation : null,
      duplicate: typeof item.duplicate === "boolean" ? item.duplicate : null,
      raw_object_id: typeof item.raw_object_id === "string" ? item.raw_object_id : null,
      pipeline_type: typeof item.pipeline_type === "string" ? item.pipeline_type : null,
    }))
    .filter((item) => item.url);
}

function runSummary(run: CrawlerRun | null): { label: string; value: number }[] {
  if (!run) return [];
  return [
    { label: "发现", value: numberFrom(run.summary, "discovered_count") },
    { label: "通过", value: numberFrom(run.summary, "accepted_count") },
    { label: "提交", value: numberFrom(run.summary, "submitted_count") },
    { label: "新增原始对象", value: numberFrom(run.summary, "raw_persisted_count") },
    { label: "去重", value: numberFrom(run.summary, "duplicate_count") },
    { label: "失败", value: numberFrom(run.summary, "failed_count") },
  ];
}

function compactHash(value: string | null | undefined): string {
  if (!value) return "";
  return value.length > 18 ? value.slice(0, 18) : value;
}

function runContentItems(run: CrawlerRun): {
  discovered: CrawlerRunSummaryItem[];
  accepted: CrawlerRunSummaryItem[];
  failures: CrawlerRunSummaryItem[];
  submitted: CrawlerRunSummaryItem[];
} {
  return {
    discovered: objectArrayFrom(run.summary, "discovered"),
    accepted: objectArrayFrom(run.summary, "accepted_snapshots"),
    failures: objectArrayFrom(run.summary, "failures"),
    submitted: objectArrayFrom(run.summary, "submitted"),
  };
}

function firstRunForPlan(runs: CrawlerRun[], planId: string): CrawlerRun | null {
  return runs.find((run) => run.plan_id === planId) ?? null;
}

function readableError(result: ApiProxyResult<unknown>): string {
  if (result.ok) return "";
  if (result.status === 404) {
    return "Crawler 控制接口暂不可用，请确认 nexus-api 已更新并重启。";
  }
  return result.message;
}

function buildPayload(
  form: PlanFormState,
  dataSourceId: string,
  topicKeywordText: string,
): Record<string, unknown> {
  const topicKeywords = splitLines(topicKeywordText);
  const base = {
    name: form.name.trim(),
    mode: form.mode,
    data_source_id: dataSourceId || null,
    execution_mode: form.executionMode,
    schedule_cron: form.executionMode === "scheduled" ? form.scheduleCron.trim() : null,
    topic_keywords: topicKeywords,
  };
  if (form.mode === "quick_start") {
    return {
      ...base,
      region_code: form.regionCode,
    };
  }
  return {
    ...base,
    target_sites: splitLines(form.targetUrls).map((url) => ({ base_url: url })),
  };
}

export function CrawlerPlansPanel() {
  const { message } = App.useApp();
  const [form, setForm] = useState<PlanFormState>(INITIAL_FORM);
  const [config, setConfig] = useState<CrawlerConfig | null>(null);
  const [regions, setRegions] = useState<CrawlerRegion[]>([]);
  const [regionSites, setRegionSites] = useState<CrawlerSites | null>(null);
  const [plans, setPlans] = useState<CrawlerPlan[]>([]);
  const [runs, setRuns] = useState<CrawlerRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [runningPlanId, setRunningPlanId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [historyDrawerOpen, setHistoryDrawerOpen] = useState(false);
  const [historyPlan, setHistoryPlan] = useState<CrawlerPlan | null>(null);
  const [historyRuns, setHistoryRuns] = useState<CrawlerRun[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const activePlans = plans.filter((plan) => plan.status !== "archived");
  const latestRun = runs[0] ?? null;
  const crawlerSourceOptions = [
    {
      value: BUILTIN_FIRECRAWL_SOURCE_ID,
      label: "Firecrawl",
    },
  ];
  const effectiveDataSourceId = form.dataSourceId || BUILTIN_FIRECRAWL_SOURCE_ID;
  const defaultTopicKeywords = Array.isArray(config?.template.default_keywords)
    ? (config.template.default_keywords as string[]).join(", ")
    : "";
  const effectiveTopicKeywords = form.topicKeywords || defaultTopicKeywords;

  const refresh = async () => {
    setLoading(true);
    setError(null);
    const [configResult, regionsResult, plansResult, runsResult] = await Promise.all([
      crawlerGet<CrawlerConfig>("/config"),
      crawlerGet<CrawlerRegion[]>("/regions"),
      crawlerGet<CrawlerPlan[]>("/plans"),
      crawlerGet<CrawlerRun[]>("/runs"),
    ]);
    const failedResult = [configResult, regionsResult, plansResult, runsResult].find(
      (result) => !result.ok,
    );
    if (failedResult) setError(readableError(failedResult));
    if (configResult.ok) {
      setConfig(configResult.data);
      setForm((prev) => ({
        ...prev,
        regionCode: prev.regionCode || configResult.data.default_region_code,
      }));
    }
    if (regionsResult.ok) setRegions(regionsResult.data);
    if (plansResult.ok) setPlans(plansResult.data);
    if (runsResult.ok) setRuns(runsResult.data);
    setLoading(false);
  };

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refresh();
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!form.regionCode) return;
    let disposed = false;
    crawlerGet<CrawlerSites>(`/regions/${encodeURIComponent(form.regionCode)}/sites`).then(
      (result) => {
        if (!disposed && result.ok) setRegionSites(result.data);
      },
    );
    return () => {
      disposed = true;
    };
  }, [form.regionCode]);

  const update = <K extends keyof PlanFormState>(key: K, value: PlanFormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const createPlan = async () => {
    if (!form.name.trim()) {
      message.error("请填写计划名称");
      return;
    }
    if (!effectiveDataSourceId) {
      message.error("请选择 Crawler 数据源");
      return;
    }
    if (form.executionMode === "scheduled" && !form.scheduleCron.trim()) {
      message.error("请填写定期执行计划");
      return;
    }
    setSaving(true);
    const result = await crawlerPost<CrawlerPlan>(
      "/plans",
      buildPayload(form, effectiveDataSourceId, effectiveTopicKeywords),
    );
    setSaving(false);
    if (!result.ok) {
      message.error(result.message);
      return;
    }
    message.success("Crawler 计划已创建");
    setPlans((prev) => [result.data, ...prev]);
    setForm({
      ...INITIAL_FORM,
      regionCode: config?.default_region_code ?? INITIAL_FORM.regionCode,
    });
    setDrawerOpen(false);
  };

  const runPlan = async (planId: string) => {
    setRunningPlanId(planId);
    const result = await crawlerPost<CrawlerRun>(`/plans/${encodeURIComponent(planId)}/run`, {});
    setRunningPlanId(null);
    if (!result.ok) {
      message.error(result.message);
      return;
    }
    message.success("Crawler run 已完成");
    setRuns((prev) => [result.data, ...prev]);
    setPlans((prev) => [...prev]);
  };

  const archivePlan = async (planId: string) => {
    const result = await crawlerPost<CrawlerPlan>(
      `/plans/${encodeURIComponent(planId)}/archive`,
      {},
    );
    if (!result.ok) {
      message.error(result.message);
      return;
    }
    message.success("计划已废弃");
    setPlans((prev) => prev.map((plan) => (plan.id === planId ? result.data : plan)));
  };

  const openHistory = async (plan: CrawlerPlan) => {
    setHistoryPlan(plan);
    setHistoryDrawerOpen(true);
    setHistoryLoading(true);
    const result = await crawlerGet<CrawlerRun[]>(
      `/runs?plan_id=${encodeURIComponent(plan.id)}`,
    );
    setHistoryLoading(false);
    if (!result.ok) {
      message.error(result.message);
      setHistoryRuns(runs.filter((run) => run.plan_id === plan.id));
      return;
    }
    setHistoryRuns(result.data);
  };

  const closeHistory = () => {
    setHistoryDrawerOpen(false);
    setHistoryPlan(null);
    setHistoryRuns([]);
  };

  const siteOptions = regionSites?.sites ?? [];

  const renderContentTable = (
    title: string,
    items: CrawlerRunSummaryItem[],
    options?: { showReason?: boolean; showSubmitted?: boolean },
  ) => (
    <div className="border-line-light rounded-md border">
      <div className="border-line-light flex items-center justify-between border-b px-3 py-2">
        <span className="text-sm font-medium">{title}</span>
        <Tag>{items.length}</Tag>
      </div>
      <Table<CrawlerRunSummaryItem>
        size="small"
        rowKey={(item, index) => `${item.url}-${index}`}
        dataSource={items}
        pagination={items.length > 5 ? { pageSize: 5, size: "small" } : false}
        locale={{ emptyText: "暂无记录" }}
        columns={[
          {
            title: "内容",
            dataIndex: "url",
            render: (_, item) => (
              <Space orientation="vertical" size={0} className="min-w-0">
                <Typography.Link
                  href={item.url}
                  target="_blank"
                  rel="noreferrer"
                  ellipsis
                  className="max-w-[520px]"
                >
                  <LinkOutlined className="mr-1" />
                  {item.title || item.url}
                </Typography.Link>
                {item.description ? (
                  <Typography.Text type="secondary" ellipsis className="max-w-[520px] text-xs">
                    {item.description}
                  </Typography.Text>
                ) : null}
                {item.source_url && item.source_url !== item.url ? (
                  <Typography.Text type="secondary" ellipsis className="max-w-[520px] text-xs">
                    来源：{item.source_url}
                  </Typography.Text>
                ) : null}
              </Space>
            ),
          },
          ...(options?.showReason
            ? [
                {
                  title: "原因",
                  dataIndex: "reason",
                  width: 120,
                  render: (_: unknown, item: CrawlerRunSummaryItem) =>
                    item.reason ? <Tag color="orange">{item.reason}</Tag> : "-",
                },
              ]
            : []),
          ...(options?.showSubmitted
            ? [
                {
                  title: "提交",
                  width: 140,
                  render: (_: unknown, item: CrawlerRunSummaryItem) => (
                    <Space orientation="vertical" size={0}>
                      {item.duplicate === true ? (
                        <Tag color="gold">重复</Tag>
                      ) : item.duplicate === false ? (
                        <Tag color="green">新增</Tag>
                      ) : (
                        <Tag>提交</Tag>
                      )}
                      {item.pipeline_type ? (
                        <span className="text-text-muted text-xs">{item.pipeline_type}</span>
                      ) : null}
                    </Space>
                  ),
                },
              ]
            : []),
          {
            title: "摘要",
            width: 160,
            render: (_, item) => (
              <Space orientation="vertical" size={0}>
                {item.content_chars ? (
                  <span className="text-text-muted text-xs">{item.content_chars} chars</span>
                ) : null}
                {item.raw_representation ? <Tag>{item.raw_representation}</Tag> : null}
                {item.content_hash ? (
                  <code className="text-text-muted font-mono text-xs">
                    {compactHash(item.content_hash)}
                  </code>
                ) : null}
              </Space>
            ),
          },
        ]}
      />
    </div>
  );

  const renderRunDetails = (run: CrawlerRun) => {
    const items = runContentItems(run);
    const filterReasons = run.summary.filter_reasons;
    const filterReasonText =
      filterReasons && typeof filterReasons === "object"
        ? Object.entries(filterReasons as Record<string, unknown>)
            .map(([key, value]) => `${key}: ${String(value)}`)
            .join(" · ")
        : "";

    return (
      <div className="grid gap-3 bg-bg-alt p-3">
        <Descriptions size="small" column={2}>
          <Descriptions.Item label="Run ID">
            <code className="font-mono text-xs">{run.id}</code>
          </Descriptions.Item>
          <Descriptions.Item label="过滤原因">
            {filterReasonText || <span className="text-text-muted">无</span>}
          </Descriptions.Item>
          <Descriptions.Item label="查询">
            <Typography.Text ellipsis className="max-w-[520px]">
              {String(run.summary.query || "")}
            </Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label="搜索范围">
            {run.summary.web_wide_search ? "全网搜索" : "目标站点"}
          </Descriptions.Item>
        </Descriptions>
        {renderContentTable("搜索候选", items.discovered)}
        {renderContentTable("通过抓取", items.accepted)}
        {renderContentTable("提交 Pipeline", items.submitted, { showSubmitted: true })}
        {renderContentTable("失败/过滤", items.failures, { showReason: true })}
      </div>
    );
  };

  return (
    <section className="mt-5">
      <div className="border-line bg-surface overflow-hidden rounded-lg border">
        <div className="border-line-light flex flex-wrap items-center justify-between gap-3 border-b px-5 py-4">
          <div>
            <h3 className="text-base font-semibold">Crawler 计划</h3>
            <div className="text-text-secondary mt-1 text-xs">
              {activePlans.length} 个活跃计划 · {runs.length} 次运行
            </div>
          </div>
          <Space>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setDrawerOpen(true)}>
              新增计划
            </Button>
            <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading}>
              刷新
            </Button>
          </Space>
        </div>

        {error && (
          <div className="px-5 pt-4">
            <Alert type="error" showIcon title={error} />
          </div>
        )}

        <div className="grid content-start gap-4 px-5 py-5">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            {runSummary(latestRun).map((item) => (
              <div key={item.label} className="border-line-light rounded-md border px-3 py-2">
                <div className="text-text-muted text-xs">{item.label}</div>
                <div className="mt-1 text-lg font-semibold">{item.value}</div>
              </div>
            ))}
          </div>

          <Table<CrawlerPlan>
            size="small"
            loading={loading}
            rowKey="id"
            dataSource={activePlans}
            pagination={{ pageSize: 8 }}
            columns={[
              {
                title: "计划",
                dataIndex: "name",
                render: (_, plan) => (
                  <Space orientation="vertical" size={0}>
                    <span className="font-medium">{plan.name}</span>
                    <span className="text-text-muted text-xs">
                      {plan.mode === "quick_start" ? "快速启动" : "通用配置"}
                      {plan.region_name ? ` · ${plan.region_name}` : ""}
                    </span>
                  </Space>
                ),
              },
              {
                title: "执行",
                dataIndex: "execution_mode",
                width: 120,
                render: (_, plan) =>
                  plan.execution_mode === "scheduled" ? (
                    <Tag color="blue">{plan.schedule_cron}</Tag>
                  ) : (
                    <Tag>运行一次</Tag>
                  ),
              },
              {
                title: "最近运行",
                width: 140,
                render: (_, plan) => {
                  const run = firstRunForPlan(runs, plan.id);
                  if (!run) return <span className="text-text-muted text-xs">未运行</span>;
                  const time = formatTime(run.started_at);
                  return (
                    <Space orientation="vertical" size={0}>
                      <StatusLabel value={run.status} />
                      <time className="text-text-muted text-xs" dateTime={time.iso}>
                        {time.display}
                      </time>
                    </Space>
                  );
                },
              },
              {
                title: "操作",
                width: 190,
                render: (_, plan) => (
                  <Space size={6}>
                    <Tooltip title="执行历史">
                      <Button
                        size="small"
                        icon={<HistoryOutlined />}
                        onClick={() => openHistory(plan)}
                      />
                    </Tooltip>
                    <Tooltip title="运行">
                      <Button
                        size="small"
                        icon={<PlayCircleOutlined />}
                        loading={runningPlanId === plan.id}
                        onClick={() => runPlan(plan.id)}
                      />
                    </Tooltip>
                    <Tooltip title="废弃">
                      <Button
                        size="small"
                        danger
                        icon={<DeleteOutlined />}
                        onClick={() => archivePlan(plan.id)}
                      />
                    </Tooltip>
                  </Space>
                ),
              },
            ]}
          />

          {latestRun ? (
            <Descriptions size="small" bordered column={2}>
              <Descriptions.Item label="最近 Run">
                <code className="font-mono text-xs">{latestRun.id}</code>
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <StatusLabel value={latestRun.status} />
              </Descriptions.Item>
              <Descriptions.Item label="配置 Hash">
                <code className="font-mono text-xs">
                  {latestRun.template_config_hash?.slice(0, 18)}
                </code>
              </Descriptions.Item>
              <Descriptions.Item label="站点 Hash">
                <code className="font-mono text-xs">
                  {latestRun.region_sites_config_hash?.slice(0, 18)}
                </code>
              </Descriptions.Item>
            </Descriptions>
          ) : (
            <Alert
              type="info"
              showIcon
              icon={<CloudDownloadOutlined />}
              title="暂无 Crawler run"
            />
          )}
        </div>
      </div>

      <Drawer
        title="新增 Crawler 计划"
        size="default"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        destroyOnClose
        footer={
          <div className="flex justify-end gap-2">
            <Button onClick={() => setDrawerOpen(false)}>取消</Button>
            <Button type="primary" icon={<PlusOutlined />} loading={saving} onClick={createPlan}>
              创建计划
            </Button>
          </div>
        }
      >
        <div className="grid content-start gap-4">
          <Tabs
            activeKey={form.mode}
            onChange={(key) => update("mode", key as PlanFormState["mode"])}
            items={[
              { key: "quick_start", label: "快速启动" },
              { key: "custom", label: "通用配置" },
            ]}
          />
          <Form layout="vertical" component="div">
            <Form.Item label="计划名称" required>
              <Input
                value={form.name}
                onChange={(event) => update("name", event.target.value)}
                placeholder="例：浙江省政策报告采集"
              />
            </Form.Item>
            <Form.Item label="归属数据源" required>
              <Select
                value={effectiveDataSourceId || undefined}
                onChange={(value) => update("dataSourceId", value)}
                options={crawlerSourceOptions}
                disabled
              />
            </Form.Item>
            {form.mode === "quick_start" ? (
              <>
                <Form.Item label="区域">
                  <Select
                    value={form.regionCode}
                    onChange={(value) => update("regionCode", value)}
                    options={regions.map((region) => ({
                      value: region.region_code,
                      label: `${region.region_name} · ${region.site_count} 站点`,
                    }))}
                  />
                </Form.Item>
                <div className="border-line-light bg-bg-alt mb-4 rounded-md border p-3">
                  <div className="mb-2 text-xs font-semibold">权威站点</div>
                  <div className="flex flex-wrap gap-2">
                    {siteOptions.map((site: CrawlerTargetSite) => (
                      <Tooltip key={site.base_url} title={site.base_url}>
                        <Tag>{site.site_name ?? site.base_url}</Tag>
                      </Tooltip>
                    ))}
                  </div>
                </div>
              </>
            ) : (
              <Form.Item label="目标站点 URL">
                <Input.TextArea
                  rows={4}
                  value={form.targetUrls}
                  onChange={(event) => update("targetUrls", event.target.value)}
                  placeholder="留空表示按主题进行全网搜索；也可填写多个 URL，逗号或换行分隔"
                />
              </Form.Item>
            )}
            <Form.Item label="主题关键词">
              <Input.TextArea
                rows={3}
                value={effectiveTopicKeywords}
                onChange={(event) => update("topicKeywords", event.target.value)}
              />
            </Form.Item>
            <Form.Item label="执行计划">
              <Select
                value={form.executionMode}
                onChange={(value) => update("executionMode", value)}
                options={[
                  { value: "run_once", label: "运行一次" },
                  { value: "scheduled", label: "定期执行" },
                ]}
              />
            </Form.Item>
            {form.executionMode === "scheduled" && (
              <Form.Item label="Cron">
                <Input
                  value={form.scheduleCron}
                  onChange={(event) => update("scheduleCron", event.target.value)}
                  placeholder="0 2 * * 1"
                />
              </Form.Item>
            )}
          </Form>
        </div>
      </Drawer>

      <Drawer
        title={historyPlan ? `${historyPlan.name} · 执行历史` : "执行历史"}
        size="large"
        open={historyDrawerOpen}
        onClose={closeHistory}
        destroyOnClose
      >
        <Table<CrawlerRun>
          size="small"
          loading={historyLoading}
          rowKey="id"
          dataSource={historyRuns}
          pagination={{ pageSize: 8 }}
          expandable={{
            expandedRowRender: renderRunDetails,
            rowExpandable: (run) => {
              const items = runContentItems(run);
              return (
                items.discovered.length > 0 ||
                items.accepted.length > 0 ||
                items.submitted.length > 0 ||
                items.failures.length > 0
              );
            },
          }}
          columns={[
            {
              title: "Run",
              dataIndex: "id",
              render: (_, run) => (
                <Space orientation="vertical" size={0}>
                  <code className="font-mono text-xs">{run.id}</code>
                  <time className="text-text-muted text-xs" dateTime={run.started_at}>
                    {formatTime(run.started_at).display}
                  </time>
                </Space>
              ),
            },
            {
              title: "状态",
              dataIndex: "status",
              width: 120,
              render: (_, run) => <StatusLabel value={run.status} />,
            },
            {
              title: "搜索/抓取",
              width: 180,
              render: (_, run) => (
                <Space size={4} wrap>
                  <Tag>发现 {numberFrom(run.summary, "discovered_count")}</Tag>
                  <Tag color="green">通过 {numberFrom(run.summary, "accepted_count")}</Tag>
                  <Tag color="red">失败 {numberFrom(run.summary, "failed_count")}</Tag>
                </Space>
              ),
            },
            {
              title: "提交",
              width: 180,
              render: (_, run) => (
                <Space size={4} wrap>
                  <Tag color="blue">提交 {numberFrom(run.summary, "submitted_count")}</Tag>
                  <Tag color="gold">去重 {numberFrom(run.summary, "duplicate_count")}</Tag>
                </Space>
              ),
            },
          ]}
        />
      </Drawer>
    </section>
  );
}
