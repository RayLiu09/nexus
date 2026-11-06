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
  crawl_policy: { max_pages: 10, categories: ["research", "pdf"] },
  search_policy: {},
  pipeline_policy: {},
  status: "active",
  created_at: "2026-10-10T00:00:00Z",
  updated_at: "2026-10-10T00:00:00Z",
};

it("copies a crawler plan through the create endpoint", async () => {
  const fetchMock = vi.fn(async (input: string, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/plans?page=1&pageSize=20"))
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
  expect(screen.queryByText("归属数据源")).not.toBeInTheDocument();
  expect(document.querySelectorAll(".ant-select-selection-item[title='研究报告']")).toHaveLength(1);
  expect(document.querySelectorAll(".ant-select-selection-item[title='PDF']")).toHaveLength(1);
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
      data_source_id: "source-1",
      crawl_policy: { max_pages: 10, categories: ["research", "pdf"] },
      target_sites: [{ base_url: "https://example.gov.cn", include_paths: ["/policy"] }],
    });
  });
});

function mockPlanForm(selectedPlan: CrawlerPlan = plan) {
  const fetchMock = vi.fn(async (input: string, init?: RequestInit) => {
    const url = String(input);
    let data: unknown = [];
    if (url.includes("/plans?")) data = [selectedPlan];
    else if (url.endsWith("/config")) data = { template: {}, default_region_code: "national" };
    else if (url.includes("/sites")) data = { sites: [] };
    else if (init?.method === "POST" || init?.method === "PUT") data = selectedPlan;
    return { json: async () => ({ ok: true, data, total: 1, traceId: null }) };
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<App><CrawlerPlansPanel /></App>);
  return fetchMock;
}

it("defaults to no category, hides the data source and submits selected categories with the built-in source", async () => {
  const fetchMock = mockPlanForm();
  fireEvent.click(screen.getByRole("button", { name: /新增计划/ }));
  fireEvent.click(screen.getByRole("tab", { name: "通用配置" }));
  expect(screen.queryByText("归属数据源")).not.toBeInTheDocument();
  const categories = screen.getByRole("combobox", { name: "搜索类别" });
  const categoryField = categories.closest(".ant-form-item")!;
  expect(categoryField.querySelectorAll(".ant-select-selection-item")).toHaveLength(0);
  expect(categoryField.compareDocumentPosition(screen.getByText("目标站点 URL")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  fireEvent.mouseDown(categories);
  fireEvent.click(await screen.findByText("研究报告", { selector: ".ant-select-item-option-content" }));
  fireEvent.click(await screen.findByText("PDF", { selector: ".ant-select-item-option-content" }));
  expect(screen.getByText("Gov", { selector: ".ant-select-item-option-content" }).closest(".ant-select-item-option"))
    .toHaveClass("ant-select-item-option-disabled");
  fireEvent.change(screen.getByPlaceholderText("例：浙江省政策报告采集"), { target: { value: "PDF 报告" } });
  fireEvent.click(screen.getByRole("button", { name: /创建计划/ }));
  await waitFor(() => {
    const request = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({
      data_source_id: "__builtin_firecrawl__",
      crawl_policy: { categories: ["research", "pdf"] },
    });
  });
});

it.each(["edit", "copy"])("lets %s replace existing categories with Gov while retaining crawl options", async (action) => {
  const fetchMock = mockPlanForm();
  fireEvent.click(await screen.findByRole("button", { name: `${action === "edit" ? "编辑计划" : "复制计划"} 政策抓取` }));
  const categories = screen.getByRole("combobox", { name: "搜索类别" });
  const clear = categories.closest(".ant-select")!.querySelector(".ant-select-clear")!;
  fireEvent.mouseDown(clear);
  fireEvent.click(clear);
  fireEvent.mouseDown(categories);
  fireEvent.click(await screen.findByText("Gov", { selector: ".ant-select-item-option-content" }));
  for (const label of ["研究报告", "PDF"]) {
    expect(screen.getByText(label, { selector: ".ant-select-item-option-content" }).closest(".ant-select-item-option"))
      .toHaveClass("ant-select-item-option-disabled");
  }
  fireEvent.click(screen.getByRole("button", { name: action === "edit" ? /保存修改/ : /创建计划/ }));
  await waitFor(() => {
    const request = fetchMock.mock.calls.find(([, init]) => init?.method === (action === "edit" ? "PUT" : "POST"));
    expect(request).toBeDefined();
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({
      data_source_id: "source-1", crawl_policy: { max_pages: 10, categories: ["gov"] },
    });
  });
});

it("edits a legacy plan with no category", async () => {
  const fetchMock = mockPlanForm({ ...plan, crawl_policy: { max_pages: 10 } });
  fireEvent.click(await screen.findByRole("button", { name: "编辑计划 政策抓取" }));
  const categories = screen.getByRole("combobox", { name: "搜索类别" });
  expect(categories.closest(".ant-form-item")!.querySelectorAll(".ant-select-selection-item")).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: /保存修改/ }));
  await waitFor(() => {
    const request = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({
      data_source_id: "source-1", crawl_policy: { max_pages: 10, categories: [] },
    });
  });
});

it("clears categories without changing an unbound legacy plan's data source", async () => {
  const fetchMock = mockPlanForm({ ...plan, data_source_id: null });
  fireEvent.click(await screen.findByRole("button", { name: "编辑计划 政策抓取" }));
  const categories = screen.getByRole("combobox", { name: "搜索类别" });
  const clear = categories.closest(".ant-select")!.querySelector(".ant-select-clear")!;
  fireEvent.mouseDown(clear);
  fireEvent.click(clear);
  fireEvent.click(screen.getByRole("button", { name: /保存修改/ }));
  await waitFor(() => {
    const request = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({
      data_source_id: null, crawl_policy: { max_pages: 10, categories: [] },
      content_goals: ["政策正文"], classification_hints: ["industry_policy"],
      target_sites: [{ base_url: "https://example.gov.cn", include_paths: ["/policy"] }],
    });
  });
});

it("shows categories for quick start and hides them for WebSearch", async () => {
  mockPlanForm();
  fireEvent.click(screen.getByRole("button", { name: /新增计划/ }));
  expect(screen.getByRole("tab", { name: "快速启动" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("combobox", { name: "搜索类别" })).toBeInTheDocument();
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "数据源类型" }));
  fireEvent.click(await screen.findByText("WebSearch", { selector: ".ant-select-item-option-content" }));
  expect(screen.queryByRole("combobox", { name: "搜索类别" })).not.toBeInTheDocument();
});

it("requests crawler plan pages from the API with 20 rows by default", async () => {
  const fetchMock = vi.fn(async (input: string) => {
    const url = String(input);
    if (url.endsWith("/plans?page=1&pageSize=20"))
      return { json: async () => ({ ok: true, data: [plan], total: 41, traceId: null }) };
    if (url.endsWith("/plans?page=2&pageSize=20"))
      return { json: async () => ({ ok: true, data: [{ ...plan, id: "plan-2", name: "第二页计划" }], total: 41, traceId: null }) };
    if (url.endsWith("/plans?page=1&pageSize=50"))
      return { json: async () => ({ ok: true, data: [plan], total: 41, traceId: null }) };
    if (url.endsWith("/plans?page=1&pageSize=100"))
      return { json: async () => ({ ok: true, data: [{ ...plan, name: "很长的爬虫计划名称".repeat(20) }], total: 41, traceId: null }) };
    if (url.includes("/runs?"))
      return { json: async () => ({ ok: true, data: [], total: 0, traceId: null }) };
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<App><CrawlerPlansPanel /></App>);
  expect(await screen.findByText("41 个活跃计划 · 0 次运行")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/crawler/plans?page=1&pageSize=20", expect.anything());
  fireEvent.click(screen.getByTitle("2"));
  expect(await screen.findByText("第二页计划")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/crawler/plans?page=2&pageSize=20", expect.anything());
  fireEvent.mouseDown(screen.getByRole("combobox"));
  fireEvent.click(await screen.findByText("50 / page"));
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith("/api/crawler/plans?page=1&pageSize=50", expect.anything());
  });
  fireEvent.mouseDown(screen.getByRole("combobox"));
  fireEvent.click(await screen.findByText("100 / page"));
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith("/api/crawler/plans?page=1&pageSize=100", expect.anything());
  });
  const table = document.querySelector(".ant-table-content table");
  expect(table).toHaveStyle({ tableLayout: "fixed" });
  expect(table?.querySelector("col")?.getAttribute("style")).toContain("260px");
  expect(document.querySelector(".ant-table-cell [title]"))?.toHaveClass("truncate");
});
