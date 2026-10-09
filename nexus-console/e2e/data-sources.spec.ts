import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { FileSyncPage, mockApi } from "./helpers/page-objects";

test.describe("File data sync page", () => {
  test.beforeEach(async ({ context, page }) => {
    await context.addCookies([{
      name: "nexus_access_token",
      value: "eA.eyJyb2xlIjoicGxhdGZvcm1fZGF0YV9hZG1pbiJ9.eA",
      domain: "127.0.0.1",
      path: "/",
    }]);
    await mockApi(page);
  });

  test("renders with correct heading hierarchy", async ({ page }) => {
    const dsPage = new FileSyncPage(page);
    await dsPage.goto();

    await expect(dsPage.heading).toHaveText("文件数据同步");
  });

  test("former data-source page is unavailable", async ({ page }) => {
    const response = await page.goto("/data-sources");
    expect(response?.status()).toBe(404);
  });

  test("offers upload and an unavailable manual NAS workflow", async ({ page }) => {
    const dsPage = new FileSyncPage(page);
    await dsPage.goto();
    await expect(page.getByRole("tab", { name: "本地上传" })).toBeVisible();
    await page.getByRole("tab", { name: "NAS 同步" }).click();
    await expect(page.getByRole("button", { name: "开始同步" })).toBeDisabled();
  });

  test("accessibility scan has zero critical violations", async ({ page }) => {
    const dsPage = new FileSyncPage(page);
    await dsPage.goto();
    await dsPage.heading.waitFor();

    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations.filter((v) => v.impact === "critical")).toEqual([]);
  });
});
