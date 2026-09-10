import { expect, test } from "@playwright/test";

test("renders the jobs ledger without page-local summary cards", async ({ context, page }) => {
  const accessToken = process.env.NEXUS_E2E_ACCESS_TOKEN;
  test.skip(!accessToken, "No real-data access token was supplied");

  await context.addCookies([
    {
      name: "nexus_access_token",
      value: accessToken!,
      domain: "localhost",
      path: "/",
    },
  ]);

  await page.goto("/jobs");

  await expect(page.getByRole("heading", { level: 1, name: "作业中心" })).toBeVisible();
  await expect(page.locator(".ant-statistic")).toHaveCount(0);
  await expect(page.locator(".ant-table")).toBeVisible();
});
