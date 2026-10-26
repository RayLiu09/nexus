import { App } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { getApiData, postApiData } from "@/lib/api";
import type { JobCollectionCategory, SyncPlan, SyncProvider, SyncRun } from "@/lib/data-sync";
import { DataSyncContent } from "./DataSyncContent";

vi.mock("@/lib/api", () => ({ getApiData: vi.fn(), postApiData: vi.fn(), deleteApiData: vi.fn() }));

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

it("creates Ministry plans using public API options and the four required fields", async () => {
  const ministry: SyncProvider = {
    ...provider("moe_major_offering"), display_name: "教育部政务服务平台",
    tenant_name: null, auth_mode: "none", execution_mode: "paged_pull", credential_status: "not_required",
    query_schema: { type: "object", required: ["year", "province", "major_name", "major_code"], properties: {
      year: { type: "integer", title: "年份" }, province: { type: "string", title: "省份/地区" },
      major_name: { type: "string", title: "专业名称" }, major_code: { type: "string", title: "专业代码" },
    } },
  };
  vi.mocked(getApiData).mockResolvedValue({ ok: true, error: null, traceId: null, total: null, data: { years: [2026, 2025], provinces: [{ code: "HeB", name: "河北省" }] } });
  render(<App><DataSyncContent initialProviders={[ministry]} initialPlans={[]} initialCatalog={[]} initialError={null} /></App>);
  expect(screen.getByText("无需认证")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /新建同步计划/ }));
  await waitFor(() => expect(getApiData).toHaveBeenCalledWith("/api/data-sync/providers/moe_major_offering/options", null));
  expect(screen.getByText("年份")).toBeInTheDocument();
  expect(screen.getByText("省份/地区")).toBeInTheDocument();
  expect(screen.getByText("专业名称")).toBeInTheDocument();
  expect(screen.getByText("专业代码")).toBeInTheDocument();
  expect(screen.queryByLabelText(/Token|API Key|租户/)).not.toBeInTheDocument();
});
