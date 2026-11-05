import { expect, test } from "@playwright/test";

const provider = {
  provider_code: "crawler_engine", display_name: "岗位需求采集", status: "enabled",
  credential_status: "available", api_server_url: "http://crawler.test", tenant_name: "测试租户",
  adapter_version: "0.2.0", query_schema: { type: "object", required: ["keywords", "regions"], properties: {
    keywords: { type: "array", maxItems: 30 }, regions: { type: "array", items: { enum: ["杭州市"] } },
    pageLimit: { enum: [10, 30, 50, 100] },
  } },
};

test.beforeEach(async ({ page, context }) => {
  const payload = Buffer.from(JSON.stringify({ role: "platform_data_admin", exp: 4102444800 })).toString("base64url");
  await context.addCookies([{ name: "nexus_access_token", value: `e2e.${payload}.signature`, url: "http://127.0.0.1:3000" }]);
  await page.route("**/api/auth/session", (route) => route.fulfill({ json: { data: {
    id: "e2e-admin", username: "e2e", displayName: "验收用户", role: "platform_data_admin", orgUnit: { id: "", name: "" },
  } } }));
  await page.route("**/api/data-sync/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() !== "GET") return route.fulfill({ json: { data: {} } });
    const data = path.endsWith("providers") ? [provider] : path.endsWith("job-catalog") ? [
      { id: "finance", name: "财经商贸类", titles: [{ id: "catalog-title", name: "目录岗位" }] },
    ] : [];
    return route.fulfill({ json: { data, meta: { total: data.length } } });
  });
});

test("custom job input and category survive comma entry and submit", async ({ page }, testInfo) => {
  if (testInfo.project.name === "chromium-tablet") await page.setViewportSize({ width: 390, height: 844 });
  const requests: Record<string, unknown>[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname === "/api/data-sync/plans") requests.push(request.postDataJSON());
  });
  await page.goto("/data-sync");
  await page.getByRole("button", { name: "刷新数据" }).click();
  await page.getByRole("button", { name: /新建同步计划/ }).click();
  await page.getByRole("textbox", { name: "计划名称" }).fill("自定义低空岗位采集");
  const category = page.getByRole("combobox", { name: "专业类别" });
  const jobs = page.getByRole("combobox", { name: /岗位名称/ });
  await jobs.fill("  低空运营专员,飞行器维修工程师，低空运营专员,");
  await expect(page.getByText("已选 2 项", { exact: true })).toBeVisible();
  await category.fill("财经商贸类");
  await category.clear();
  await expect(page.getByText("已选 2 项", { exact: true })).toBeVisible();
  await category.fill("低空经济类");
  await page.getByRole("checkbox", { name: "全选区域" }).check();
  // A final job without a comma must be committed when the user clicks Create.
  await jobs.fill("无人机驾驶员");
  await page.getByRole("button", { name: "创建计划" }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toEqual({ name: "自定义低空岗位采集", provider_code: "crawler_engine", frequency: "1_month",
    query_config: { keywords: ["低空运营专员", "飞行器维修工程师", "无人机驾驶员"], professional_category: "低空经济类", regions: ["杭州市"], pageLimit: 30 },
  });
});

test("30 custom jobs submit without a category and 31 jobs block submission", async ({ page }) => {
  const requests: Record<string, unknown>[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname === "/api/data-sync/plans") requests.push(request.postDataJSON());
  });
  await page.goto("/data-sync");
  await page.getByRole("button", { name: "刷新数据" }).click();
  await page.getByRole("button", { name: /新建同步计划/ }).click();
  await page.getByRole("textbox", { name: "计划名称" }).fill("岗位数量边界");
  const jobs = page.getByRole("combobox", { name: /岗位名称/ });
  const keywords = Array.from({ length: 30 }, (_, i) => `自定义岗位${i}`);
  await jobs.fill(keywords.join(",") + ",第31个岗位,");
  await page.getByRole("checkbox", { name: "全选区域" }).check();
  await page.getByRole("button", { name: "创建计划" }).click();
  await expect(page.getByText("一次最多支持 30 个岗位", { exact: true })).toBeVisible();
  expect(requests).toHaveLength(0);
  // Remove the last tag through the input, retaining exactly thirty names.
  await jobs.focus();
  await jobs.press("Backspace");
  await expect(page.getByText("已选 30 项", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "创建计划" }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0].query_config).toEqual({ keywords, regions: ["杭州市"], pageLimit: 30 });
});
