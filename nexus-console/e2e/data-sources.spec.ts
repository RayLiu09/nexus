import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { DataSourcesPage, mockApi } from "./helpers/page-objects";

test.describe("Data sources page", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page);
  });

  test("renders with correct heading hierarchy", async ({ page }) => {
    const dsPage = new DataSourcesPage(page);
    await dsPage.goto();

    await expect(dsPage.heading).toBeVisible();
    // h1 should exist
    await expect(page.locator("h1").first()).toBeVisible();
  });

  test("renders data source entries when API returns items", async ({ page }) => {
    const dsPage = new DataSourcesPage(page);
    await dsPage.goto();

    // Should show one of the mocked data source names
    await expect(page.getByText("HR 系统").or(page.getByText("文档库"))).toBeVisible({ timeout: 10000 });
  });

  test("accessibility scan has zero critical violations", async ({ page }) => {
    const dsPage = new DataSourcesPage(page);
    await dsPage.goto();
    await dsPage.heading.waitFor();

    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations.filter((v) => v.impact === "critical")).toEqual([]);
  });
});
