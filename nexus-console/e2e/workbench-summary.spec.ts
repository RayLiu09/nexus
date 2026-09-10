import { expect, test } from "@playwright/test";

test("renders complete workbench summary instead of the first list page", async ({
  context,
  page,
}) => {
  const accessToken = process.env.NEXUS_E2E_ACCESS_TOKEN;
  const expectedAssetCount = process.env.NEXUS_E2E_WORKBENCH_ASSET_COUNT;
  const expectedSucceededJobs = process.env.NEXUS_E2E_WORKBENCH_SUCCEEDED_JOBS;
  const expectedFailedJobs = process.env.NEXUS_E2E_WORKBENCH_FAILED_JOBS;
  test.skip(
    !accessToken || !expectedAssetCount || !expectedSucceededJobs || !expectedFailedJobs,
    "No real-data Workbench summary expectations were supplied",
  );

  await context.addCookies([
    {
      name: "nexus_access_token",
      value: accessToken!,
      domain: "localhost",
      path: "/",
    },
  ]);

  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.goto("/workbench");

  await expect(page.getByRole("heading", { level: 1, name: "工作台" })).toBeVisible();
  const assetStatistic = page.locator(".ant-statistic").filter({ hasText: "数据资产总量" });
  await expect
    .poll(async () =>
      (await assetStatistic.locator(".ant-statistic-content-value").textContent())?.replace(
        /,/g,
        "",
      ),
    )
    .toBe(expectedAssetCount);
  await expect(page.locator(".metric-hero")).toContainText(`${expectedSucceededJobs} 成功`);
  await expect(page.locator(".metric-hero")).toContainText(`${expectedFailedJobs} 失败`);
  await expect(page.getByText("已治理引用", { exact: true })).toBeVisible();
  expect(pageErrors).toEqual([]);
});
