import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { JobsPage, mockApi } from "./helpers/page-objects";

test.describe("Jobs center page", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page);
  });

  test("renders with correct heading", async ({ page }) => {
    const jobsPage = new JobsPage(page);
    await jobsPage.goto();

    await expect(jobsPage.heading).toBeVisible();
  });

  test("renders job entries from API data", async ({ page }) => {
    const jobsPage = new JobsPage(page);
    await jobsPage.goto();

    // The page should render job entries
    // Jobs are shown as short IDs (8 chars + ... + 4 chars)
    await expect(page.locator(".mono-cell").first()).toBeVisible({ timeout: 10000 });
  });

  test("accessibility scan has zero critical violations", async ({ page }) => {
    const jobsPage = new JobsPage(page);
    await jobsPage.goto();
    await jobsPage.heading.waitFor();

    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations.filter((v) => v.impact === "critical")).toEqual([]);
  });
});
