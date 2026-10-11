import { App } from "antd";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import type { CrawlerPlan } from "@/lib/api";
import { CrawlerPlansPanel } from "./CrawlerPlansPanel";

vi.stubGlobal("ResizeObserver", class {
  observe() {}
  unobserve() {}
  disconnect() {}
});

const plan: CrawlerPlan = {
  id: "plan-1",
  name: "政策抓取",
  connector_type: "firecrawl",
  connector_version: "v2",
  mode: "custom",
  data_source_id: "source-1",
  template_code: null,
  template_version: null,
  region_code: null,
  region_name: null,
  topic_keywords: ["低空经济"],
  content_goals: ["政策正文"],
  classification_hints: ["industry_policy"],
  target_sites: [{ base_url: "https://example.gov.cn", include_paths: ["/policy"] }],
  execution_mode: "run_once",
  schedule_cron: null,
  schedule_paused: false,
  next_run_at: null,
  crawl_policy: { max_pages: 10 },
  search_policy: {},
  pipeline_policy: {},
  status: "active",
  created_at: "2026-10-10T00:00:00Z",
  updated_at: "2026-10-10T00:00:00Z",
};

it("copies a crawler plan through the create endpoint", async () => {
  const fetchMock = vi.fn(async (input: string, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/plans?pageSize=100"))
      return { json: async () => ({ ok: true, data: [plan], total: 1, traceId: null }) };
    if (url.includes("/runs?"))
      return { json: async () => ({ ok: true, data: [], total: 0, traceId: null }) };
    if (url.endsWith("/config"))
      return { json: async () => ({ ok: true, data: { template: {}, default_region_code: "national" } }) };
    if (url.endsWith("/regions"))
      return { json: async () => ({ ok: true, data: [] }) };
    if (url.includes("/regions/national/sites"))
      return { json: async () => ({ ok: true, data: { sites: [] } }) };
    if (url.endsWith("/plans") && init?.method === "POST")
      return { json: async () => ({ ok: true, data: { ...plan, id: "plan-2" } }) };
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<App><CrawlerPlansPanel /></App>);
  const copyButton = await screen.findByRole("button", { name: "复制计划 政策抓取" });
  await act(async () => { fireEvent.click(copyButton); });
  expect(screen.getByText("复制 Crawler 计划")).toBeInTheDocument();
  expect(screen.getByPlaceholderText("例：浙江省政策报告采集")).toHaveValue("政策抓取 副本");
  fireEvent.click(screen.getByRole("button", { name: /创建计划/ }));

  await waitFor(() => {
    const createCall = fetchMock.mock.calls.find(([url, init]) =>
      String(url).endsWith("/plans") && init?.method === "POST",
    );
    expect(createCall).toBeDefined();
    const payload = JSON.parse(String(createCall?.[1]?.body));
    expect(payload).toMatchObject({
      name: "政策抓取 副本",
      topic_keywords: ["低空经济"],
      content_goals: ["政策正文"],
      classification_hints: ["industry_policy"],
      crawl_policy: { max_pages: 10 },
      target_sites: [{ base_url: "https://example.gov.cn", include_paths: ["/policy"] }],
    });
  });
});
