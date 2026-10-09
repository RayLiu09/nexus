import { App } from "antd";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import type { JobCollectionCategory, SyncPlan, SyncProvider } from "@/lib/data-sync";
import { DataSyncContent } from "./DataSyncContent";

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
