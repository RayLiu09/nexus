import { App } from "antd";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { getApiData, postApiData, putApiData } from "@/lib/api";
import type { JobCollectionCategory, SyncPlan, SyncProvider, SyncRun } from "@/lib/data-sync";
import { DataSyncContent } from "./DataSyncContent";

vi.mock("@/lib/api", () => ({ getApiData: vi.fn(), postApiData: vi.fn(), putApiData: vi.fn(), deleteApiData: vi.fn() }));

beforeEach(() => vi.clearAllMocks());

vi.stubGlobal("ResizeObserver", class {
  observe() {}
  unobserve() {}
  disconnect() {}
});

const querySchema = {
  type: "object",
  properties: {
    keywords: { type: "array", title: "岗位名称" },
    regions: { type: "array", title: "区域", items: { enum: ["杭州市", "上海市"] } },
    pageLimit: { enum: [10, 30, 50, 100], default: 30, title: "页数" },
  },
  required: ["keywords", "regions"],
};

const provider = (code: string): SyncProvider => ({
  provider_code: code,
  display_name: code === "mock" ? "Mock Provider" : "岗位需求采集",
  api_server_url: "http://example.test:8080",
  tenant_name: "测试租户",
  credential_status: "available",
  adapter_version: "0.2.0",
  status: "enabled",
  query_schema: querySchema,
});

const mockPlan: SyncPlan = {
  id: "mock-plan",
  name: "旧 Mock 计划",
  provider_code: "mock",
  status: "active",
  frequency: "1_month",
  query_config: {},
  next_run_at: null,
  last_run_at: null,
  created_at: "2026-10-08T00:00:00Z",
};

const catalog: JobCollectionCategory[] = [{
  id: "finance",
  name: "财经商贸类",
  titles: [{ id: "job-1", name: "数据化运营助理" }],
}];

it("paginates plans, changes page size, and resets the page for provider filters", async () => {
  const plans = Array.from({ length: 65 }, (_, i): SyncPlan => ({
    ...mockPlan, id: `plan-${i + 1}`, name: `同步计划 ${i + 1}`,
    provider_code: i < 60 ? "crawler_engine" : "moe_major_offering",
  }));
  render(<App><DataSyncContent initialProviders={[provider("crawler_engine"), { ...provider("moe_major_offering"), display_name: "教育部政务服务平台" }]}
    initialPlans={plans} initialCatalog={catalog} initialError={null} /></App>);
  const list = within(screen.getByRole("region", { name: "同步计划" }));
  expect(list.getByText("同步计划 1")).toBeInTheDocument();
  expect(list.queryByText("同步计划 11")).not.toBeInTheDocument();
  fireEvent.click(list.getByTitle("2"));
  expect(list.getByText("同步计划 11")).toBeInTheDocument();
  expect(list.queryByText("同步计划 1")).not.toBeInTheDocument();
  fireEvent.mouseDown(list.getByRole("combobox", { name: "Page Size" }));
  fireEvent.click(screen.getByRole("option", { name: "20 / page" }));
  await waitFor(() => expect(list.getByText("同步计划 1")).toBeInTheDocument());
  expect(list.getByText("同步计划 20")).toBeInTheDocument();
  expect(list.queryByText("同步计划 21")).not.toBeInTheDocument();
  fireEvent.click(list.getByTitle("3"));
  expect(list.getByText("同步计划 41")).toBeInTheDocument();
  fireEvent.mouseDown(list.getByRole("combobox", { name: "按 Provider 筛选计划" }));
  // The second provider contains only five plans and must return to page one.
  fireEvent.click(screen.getAllByText("教育部政务服务平台").find(
    (element) => element.classList.contains("ant-select-item-option-content"),
  )!);
  await waitFor(() => expect(list.getByText("同步计划 61")).toBeInTheDocument());
  expect(list.getByText("同步计划 65")).toBeInTheDocument();
  expect(list.queryByText("同步计划 41")).not.toBeInTheDocument();
});

it("clamps the plan page after refresh and resets when including deleted plans", async () => {
  const plans = Array.from({ length: 21 }, (_, i): SyncPlan => ({
    ...mockPlan, id: `plan-${i + 1}`, name: `同步计划 ${i + 1}`, provider_code: "crawler_engine",
  }));
  vi.mocked(getApiData).mockImplementation(async (path) => ({
    data: path.includes("/providers") ? [provider("crawler_engine")] : path.includes("/job-catalog") ? catalog : plans.slice(0, 15),
    ok: true, error: null, traceId: null, total: 15,
  }));
  render(<App><DataSyncContent initialProviders={[provider("crawler_engine")]}
    initialPlans={plans} initialCatalog={catalog} initialError={null} /></App>);
  const list = within(screen.getByRole("region", { name: "同步计划" }));
  fireEvent.click(list.getByTitle("3"));
  expect(list.getByText("同步计划 21")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "刷新数据" }));
  await waitFor(() => expect(list.getByText("同步计划 11")).toBeInTheDocument());
  expect(list.getByText("同步计划 15")).toBeInTheDocument();
  expect(list.queryByText("同步计划 21")).not.toBeInTheDocument();
  fireEvent.click(list.getByRole("checkbox", { name: "包含已删除计划" }));
  await waitFor(() => expect(list.getByText("同步计划 1")).toBeInTheDocument());
  expect(getApiData).toHaveBeenCalledWith("/api/data-sync/plans", [], { include_deleted: "true" });
});

it("shows only the real provider and opens the job-collection plan controls", () => {
  render(
    <App>
      <DataSyncContent
        initialProviders={[provider("mock"), provider("crawler_engine")]}
        initialPlans={[mockPlan]}
        initialCatalog={catalog}
        initialError={null}
      />
    </App>,
  );

  expect(screen.queryByText("Mock Provider")).not.toBeInTheDocument();
  expect(screen.queryByText("旧 Mock 计划")).not.toBeInTheDocument();
  expect(screen.getByText("岗位需求采集")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /新建同步计划/ }));
  expect(screen.getByText("专业类别")).toBeInTheDocument();
  expect(screen.getByText("岗位名称")).toBeInTheDocument();
  expect(screen.getByText("区域")).toBeInTheDocument();
  expect(screen.getByText("页数")).toBeInTheDocument();
  expect(screen.getByText("30 页")).toBeInTheDocument();
});

it("opens run history after pausing a plan and shows the pending run pause", async () => {
  const plan: SyncPlan = { ...mockPlan, id: "crawler-plan", name: "杭州岗位", provider_code: "crawler_engine" };
  const run: SyncRun = {
    id: "run-1", data_sync_config_id: plan.id, provider_code: "crawler_engine",
    adapter_version: "0.2.0", status: "running", external_status: "pausing",
    external_task_id: "external-1", processed_count: 1, success_count: 1,
    failure_count: 0, skipped_count: 0, failure_summary: null,
    queued_at: "2026-10-09T00:00:00Z", updated_at: "2026-10-09T00:01:00Z",
  };
  vi.mocked(postApiData).mockResolvedValue({ data: {} });
  vi.mocked(getApiData).mockImplementation(async (path) => ({
    data: path.includes("/runs") ? [run] : path.includes("/providers") ? [provider("crawler_engine")] :
      path.includes("/job-catalog") ? catalog : [{ ...plan, status: "paused" }],
    ok: true, error: null, traceId: null, total: 1,
  }));
  render(
    <App>
      <DataSyncContent
        initialProviders={[provider("crawler_engine")]}
        initialPlans={[plan]}
        initialCatalog={catalog}
        initialError={null}
      />
    </App>,
  );
  fireEvent.click(screen.getByRole("button", { name: "暂停计划 杭州岗位" }));
  await waitFor(() => expect(screen.getByText("暂停中")).toBeInTheDocument());
  expect(screen.getByText("运行记录 · 杭州岗位")).toBeInTheDocument();
  expect(postApiData).toHaveBeenCalledWith("/api/data-sync/plans/crawler-plan/pause", {});
});

it("opens the paused run and its resume action after resuming a plan", async () => {
  const plan: SyncPlan = {
    ...mockPlan, id: "crawler-plan", name: "杭州岗位",
    provider_code: "crawler_engine", status: "paused",
  };
  const run: SyncRun = {
    id: "run-2", data_sync_config_id: plan.id, provider_code: "crawler_engine",
    adapter_version: "0.2.0", status: "paused", external_status: "paused",
    external_task_id: "external-2", processed_count: 1, success_count: 1,
    failure_count: 0, skipped_count: 0, failure_summary: null,
    queued_at: "2026-10-09T00:00:00Z", updated_at: "2026-10-09T00:01:00Z",
  };
  vi.mocked(postApiData).mockResolvedValue({ data: {} });
  vi.mocked(getApiData).mockImplementation(async (path) => ({
    data: path.includes("/runs") ? [run] : path.includes("/providers") ? [provider("crawler_engine")] :
      path.includes("/job-catalog") ? catalog : [{ ...plan, status: "active" }],
    ok: true, error: null, traceId: null, total: 1,
  }));
  render(
    <App>
      <DataSyncContent
        initialProviders={[provider("crawler_engine")]}
        initialPlans={[plan]}
        initialCatalog={catalog}
        initialError={null}
      />
    </App>,
  );
  fireEvent.click(screen.getByRole("button", { name: "恢复计划 杭州岗位" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "恢复运行 run-2" })).toBeInTheDocument());
  expect(screen.getByText("运行记录 · 杭州岗位")).toBeInTheDocument();
  expect(postApiData).toHaveBeenCalledWith("/api/data-sync/plans/crawler-plan/resume", {});
});

it("copies a sync plan into a new prefilled plan", async () => {
  const plan: SyncPlan = {
    ...mockPlan,
    id: "job-plan",
    name: "杭州岗位",
    provider_code: "crawler_engine",
    query_config: { keywords: ["数据化运营助理"], regions: ["杭州市"], pageLimit: 30 },
  };
  vi.mocked(postApiData).mockResolvedValue({ data: {} });
  vi.mocked(getApiData).mockImplementation(async (path) => ({
    data: path.includes("/providers") ? [provider("crawler_engine")] :
      path.includes("/job-catalog") ? catalog : [plan],
    ok: true, error: null, traceId: null, total: 1,
  }));
  render(
    <App>
      <DataSyncContent
        initialProviders={[provider("crawler_engine")]}
        initialPlans={[plan]}
        initialCatalog={catalog}
        initialError={null}
      />
    </App>,
  );

  fireEvent.click(screen.getByRole("button", { name: "复制计划 杭州岗位" }));
  expect(screen.getByText("复制同步计划 · 岗位需求采集")).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "计划名称" })).toHaveValue("杭州岗位 副本");
  expect(screen.getAllByText(/已选/).map((item) => item.textContent)).toEqual(["已选 1 项", "已选 1 项"]);
  fireEvent.click(screen.getByRole("button", { name: "创建计划" }));
  await waitFor(() => expect(postApiData).toHaveBeenCalledWith("/api/data-sync/plans", {
    name: "杭州岗位 副本",
    provider_code: "crawler_engine",
    frequency: "1_month",
    query_config: plan.query_config,
  }));
});

it("selects every job title and region for a new collection plan", async () => {
  vi.mocked(postApiData).mockResolvedValue({ data: {} });
  vi.mocked(getApiData).mockImplementation(async (path) => ({
    data: path.includes("/providers") ? [provider("crawler_engine")] :
      path.includes("/job-catalog") ? catalog : [],
    ok: true, error: null, traceId: null, total: 0,
  }));
  render(
    <App>
      <DataSyncContent
        initialProviders={[provider("crawler_engine")]}
        initialPlans={[]}
        initialCatalog={[{
          ...catalog[0],
          titles: [...catalog[0].titles, { id: "job-2", name: "跨境电商运营" }],
        }]}
        initialError={null}
      />
    </App>,
  );

  fireEvent.click(screen.getByRole("button", { name: /新建同步计划/ }));
  fireEvent.change(screen.getByRole("textbox", { name: "计划名称" }), {
    target: { value: "全选岗位计划" },
  });
  fireEvent.click(screen.getByRole("checkbox", { name: "全选岗位名称" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "全选区域" }));
  expect(screen.getAllByText(/已选/).map((item) => item.textContent)).toEqual(["已选 2 项", "已选 2 项"]);
  fireEvent.click(screen.getByRole("checkbox", { name: "全选区域" }));
  expect(screen.getAllByText(/已选/).map((item) => item.textContent)).toEqual(["已选 2 项", "已选 0 项"]);
  fireEvent.click(screen.getByRole("checkbox", { name: "全选区域" }));
  fireEvent.click(screen.getByRole("button", { name: "创建计划" }));

  await waitFor(() => expect(postApiData).toHaveBeenCalledWith("/api/data-sync/plans", {
    name: "全选岗位计划",
    provider_code: "crawler_engine",
    frequency: "1_month",
    query_config: {
      keywords: ["数据化运营助理", "跨境电商运营"],
      regions: ["杭州市", "上海市"],
      pageLimit: 30,
    },
  }));
});

it("blocks a fully selected collection plan above the upstream combination limit", async () => {
  const largeCatalog: JobCollectionCategory[] = [{
    ...catalog[0],
    titles: Array.from({ length: 51 }, (_, index) => ({
      id: `job-${index}`,
      name: `岗位${index}`,
    })),
  }];
  render(
    <App>
      <DataSyncContent
        initialProviders={[provider("crawler_engine")]}
        initialPlans={[]}
        initialCatalog={largeCatalog}
        initialError={null}
      />
    </App>,
  );
  fireEvent.click(screen.getByRole("button", { name: /新建同步计划/ }));
  fireEvent.change(screen.getByRole("textbox", { name: "计划名称" }), {
    target: { value: "超限计划" },
  });
  fireEvent.click(screen.getByRole("checkbox", { name: "全选岗位名称" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "全选区域" }));

  expect(screen.getByText("岗位与城市组合不能超过 100 组，请缩小选择范围")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "创建计划" }));
  await waitFor(() => expect(postApiData).not.toHaveBeenCalled());
});

const ministry: SyncProvider = {
  ...provider("moe_major_offering"), display_name: "教育部政务服务平台",
  tenant_name: null, auth_mode: "none", execution_mode: "paged_pull", credential_status: "not_required",
  query_schema: { type: "object", required: ["year"], properties: {
    year: { type: "integer", title: "年份", default: 2026 }, province: { anyOf: [{ type: "string" }, { type: "null" }], title: "省份/地区" },
    major_name: { anyOf: [{ type: "string" }, { type: "null" }], title: "专业名称" }, major_code: { anyOf: [{ type: "string" }, { type: "null" }], title: "专业代码" },
  } },
};

it("creates a Ministry plan with the current year and empty optional filters without requesting dictionaries", async () => {
  vi.mocked(getApiData).mockResolvedValue({ ok: true, error: null, traceId: null, total: null, data: [] });
  vi.mocked(postApiData).mockResolvedValue({ data: {} });
  render(<App><DataSyncContent initialProviders={[ministry]} initialPlans={[]} initialCatalog={[]} initialError={null} /></App>);
  expect(screen.getByText("无需认证")).toBeInTheDocument();
  const currentYear = new Date().getFullYear();
  fireEvent.click(screen.getByRole("button", { name: /新建同步计划/ }));
  expect(await screen.findByText(String(currentYear))).toBeInTheDocument();
  for (const label of ["省份/地区", "专业名称", "专业代码"]) {
    expect(screen.getByText(label).closest("label")).not.toHaveClass("ant-form-item-required");
  }
  expect(screen.queryByLabelText(/Token|API Key|租户/)).not.toBeInTheDocument();
  expect(getApiData).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole("textbox", { name: "计划名称" }), { target: { value: "年度备案" } });
  fireEvent.click(screen.getByRole("button", { name: "创建计划" }));
  await waitFor(() => expect(postApiData).toHaveBeenCalled());
  const payload = vi.mocked(postApiData).mock.calls[0][1] as { query_config: Record<string, unknown>; frequency: string };
  expect(payload.frequency).toBe("1_year");
  expect(Object.fromEntries(Object.entries(payload.query_config).filter(([, value]) => value !== undefined))).toEqual({ year: currentYear });
  expect(vi.mocked(getApiData).mock.calls.every(([path]) => !path.endsWith("/options"))).toBe(true);
});

it("uses fixed Ministry province codes and preserves the year of an existing plan", async () => {
  const existing: SyncPlan = { ...mockPlan, id: "ministry", name: "历史备案", provider_code: "moe_major_offering", query_config: { year: 2025, province: "HeB", major_name: "电子商务", major_code: "530701" } };
  render(<App><DataSyncContent initialProviders={[ministry]} initialPlans={[existing]} initialCatalog={[]} initialError={null} /></App>);
  fireEvent.click(screen.getByRole("button", { name: "编辑计划 历史备案" }));
  expect(await screen.findByText("2025")).toBeInTheDocument();
  expect(screen.getByText("河北省")).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "专业代码" })).toHaveValue("530701");
  expect(getApiData).not.toHaveBeenCalled();
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "省份/地区" }));
  expect(await screen.findByText("北京市")).toBeInTheDocument();
});

it("saves an edited Ministry plan through the PUT mutation helper", async () => {
  vi.mocked(getApiData).mockResolvedValue({ ok: true, error: null, traceId: null, total: null, data: [] });
  vi.mocked(putApiData).mockResolvedValue({ data: {} });
  const existing: SyncPlan = { ...mockPlan, id: "ministry", name: "历史备案", provider_code: "moe_major_offering", frequency: "1_year", query_config: { year: 2025 } };
  render(<App><DataSyncContent initialProviders={[ministry]} initialPlans={[existing]} initialCatalog={[]} initialError={null} /></App>);
  fireEvent.click(screen.getByRole("button", { name: "编辑计划 历史备案" }));
  fireEvent.change(screen.getByRole("textbox", { name: "计划名称" }), { target: { value: "修改备案" } });
  fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
  await waitFor(() => expect(putApiData).toHaveBeenCalledWith("/api/data-sync/plans/ministry", expect.objectContaining({ name: "修改备案", query_config: { year: 2025 } })));
});

it("submits year 2035 and the selected optional Ministry filters using original province codes", async () => {
  vi.mocked(getApiData).mockResolvedValue({ ok: true, error: null, traceId: null, total: null, data: [] });
  vi.mocked(postApiData).mockResolvedValue({ data: {} });
  render(<App><DataSyncContent initialProviders={[ministry]} initialPlans={[]} initialCatalog={[]} initialError={null} /></App>);
  fireEvent.click(screen.getByRole("button", { name: /新建同步计划/ }));
  fireEvent.mouseDown(await screen.findByRole("combobox", { name: "年份" }));
  fireEvent.click(await screen.findByText("2035"));
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "省份/地区" }));
  fireEvent.click(await screen.findByText("河北省"));
  fireEvent.change(screen.getByRole("textbox", { name: "计划名称" }), { target: { value: "选填备案" } });
  fireEvent.change(screen.getByRole("textbox", { name: "专业名称" }), { target: { value: "电子商务" } });
  fireEvent.change(screen.getByRole("textbox", { name: "专业代码" }), { target: { value: "530701" } });
  fireEvent.click(screen.getByRole("button", { name: "创建计划" }));
  await waitFor(() => expect(postApiData).toHaveBeenCalledWith("/api/data-sync/plans", expect.objectContaining({
    query_config: { year: 2035, province: "HeB", major_name: "电子商务", major_code: "530701" },
  })));
});
