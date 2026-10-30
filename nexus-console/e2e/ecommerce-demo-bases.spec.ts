import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const route = "/asset-center/market/ecommerce-demo-bases";
// Run against an authenticated API with the complete persisted source snapshot.
// A token file allows local isolated acceptance without exposing tokens in argv.
const token = process.env.NEXUS_E2E_ACCESS_TOKEN_FILE
  ? readFileSync(process.env.NEXUS_E2E_ACCESS_TOKEN_FILE, "utf8").trim()
  : process.env.NEXUS_E2E_ACCESS_TOKEN;

async function readyCharts(page: Page) {
  await expect(page.getByRole("img", { name: "省份基地数量柱状图" })).toHaveAttribute(
    "data-chart-state",
    "ready",
  );
  await expect(page.getByRole("img", { name: "中国省份基地分布地图" })).toHaveAttribute(
    "data-chart-state",
    "ready",
  );
}

test.describe("电商示范基地完整数据库快照", () => {
  test.skip(!token, "Supply a valid Console token and a database with the 312-record snapshot");
  test.beforeEach(async ({ context, baseURL }) => {
    await context.addCookies([
      { name: "nexus_access_token", value: token!, url: baseURL!, httpOnly: true },
    ]);
  });

  test("入口计数、国家图表联动、批次及 URL 恢复", async ({ page }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("/asset-center");
    await page.getByRole("link", { name: /电商示范基地，312 条/ }).click();
    await expect(page.getByRole("heading", { name: "国家电子商务示范基地" })).toBeVisible();
    await expect(page.getByRole("status")).toContainText("170");
    for (const label of ["首批（34）", "第二批（63）", "增补（73）"]) {
      await expect(page.getByRole("button", { name: label, exact: true })).toBeVisible();
    }
    await readyCharts(page);
    await expect(
      page.getByRole("img", { name: "中国省份基地分布地图" }).locator("svg path").first(),
    ).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({ path: testInfo.outputPath("national.png"), fullPage: true });

    // The largest column is Jiangsu (15), rendered by the actual ECharts SVG.
    await page
      .getByRole("img", { name: "省份基地数量柱状图" })
      .locator('path[fill="#3b82f6"]')
      .first()
      .click();
    await expect(page).toHaveURL(/province_code=320000/);
    await expect(page.getByRole("status")).toContainText("15");
    await page.getByRole("button", { name: "全部地区", exact: true }).click();
    await expect(page.getByRole("status")).toContainText("170");
    await readyCharts(page);
    // Jiangsu is also the darkest map region in the full national snapshot.
    await page
      .getByRole("img", { name: "中国省份基地分布地图" })
      .locator('path[fill="rgb(29,78,216)"]')
      .first()
      .click();
    await expect(page).toHaveURL(/province_code=320000/);
    await expect(page.getByRole("status")).toContainText("15");
    await page.getByRole("button", { name: "全部地区", exact: true }).click();
    await expect(page.getByRole("status")).toContainText("170");
    await page.getByRole("button", { name: "首批（34）", exact: true }).click();
    await expect(page).toHaveURL(/batch=first/);
    await expect(page.getByRole("status")).toContainText("34");
    await page.reload();
    await expect(page.getByRole("status")).toContainText("34");
    await page.goBack();
    await expect(page.getByRole("status")).toContainText("170");
    expect(errors).toEqual([]);
  });

  test("省份列表、分页、组合筛选及空结果", async ({ page }, testInfo) => {
    const writes: string[] = [];
    page.on("request", (request) => {
      if (["POST", "PUT", "PATCH", "DELETE"].includes(request.method())) writes.push(request.url());
    });
    await page.goto(`${route}?level=provincial`);
    await expect(page.getByRole("heading", { name: "省级电子商务示范基地" })).toBeVisible();
    await expect(page.getByText("共 142 条", { exact: true })).toBeVisible();
    await expect(page.getByRole("img", { name: "中国省份基地分布地图" })).toHaveCount(0);
    await expect(page.getByRole("columnheader", { name: "来源发布时间" })).toBeVisible();
    const rows = page.locator(".ant-table-tbody > tr.ant-table-row");
    await expect(rows).toHaveCount(20);
    await page.locator(".ant-pagination-next").click();
    await expect(page).toHaveURL(/page=2/);
    await expect(rows.first().locator("td").first()).toHaveText("21");
    await page.screenshot({ path: testInfo.outputPath("provincial.png"), fullPage: true });
    await page.getByRole("combobox", { name: "省份", exact: true }).click();
    await page
      .locator(".ant-select-item-option-content")
      .getByText("江苏省", { exact: true })
      .click();
    await page.getByRole("button", { name: /检索/ }).click();
    await expect(page).toHaveURL(/province_code=320000/);
    await expect(page.getByText("共 79 条", { exact: true })).toBeVisible();
    await expect(rows.first().locator("td").first()).toHaveText("1");
    await page
      .getByRole("textbox", { name: "基地名称", exact: true })
      .fill("不存在的基地-acceptance");
    await page.getByRole("button", { name: /检索/ }).click();
    await expect(page.getByText("未找到匹配基地", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: /重置/ }).click();
    await expect(page.getByText("共 142 条", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: /编辑|删除|新增|导入/ })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    expect(writes).toEqual([]);
  });

  test("地图失败保留列表并允许重试", async ({ page }) => {
    await page.route("**/maps/china-provinces.json", (request) => request.abort());
    await page.goto(route);
    await expect(
      page.getByText("图表加载失败，仍可通过列表查看基地。", { exact: true }),
    ).toBeVisible();
    await expect(page.locator(".ant-table-tbody > tr.ant-table-row")).toHaveCount(20);
    await page.unroute("**/maps/china-provinces.json");
    await page.getByRole("button", { name: "重新加载图表", exact: true }).click();
    await readyCharts(page);
  });
});
