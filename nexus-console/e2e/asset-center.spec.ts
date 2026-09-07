import { expect, test } from "@playwright/test";

test.describe("Asset Center IA-1", () => {
  test.beforeEach(async ({ context }) => {
    await context.addCookies([
      {
        name: "nexus_access_token",
        value: process.env.NEXUS_E2E_ACCESS_TOKEN ?? "e2e-fake-token",
        domain: "localhost",
        path: "/",
      },
    ]);
  });

  test("renders five business domains and fixed navigation", async ({ page }, testInfo) => {
    await page.goto("/asset-center");

    await expect(page.getByRole("heading", { level: 1, name: "资产中心" })).toBeVisible();
    await expect(page.locator("main").getByRole("article")).toHaveCount(5);
    await expect(page.getByRole("heading", { name: "产业政策数据" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "专业数据" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "市场数据" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "教材资源数据" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "用户行为数据" })).toBeVisible();
    await expect(page.getByRole("link", { name: /标准课程库，[\d,]+ 条/ })).toBeVisible();
    await expect(page.getByText("产业画像")).toHaveCount(0);
    await expect(page.getByRole("link", { name: "智能检索", exact: true })).toHaveCount(1);
    await expect(page.getByRole("link", { name: "检索联调" })).toHaveCount(0);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);

    if (process.env.NEXUS_CAPTURE_SCREENSHOTS) {
      await page.screenshot({
        path: `/tmp/asset-center-${testInfo.project.name}.png`,
        fullPage: true,
      });
    }
  });

  test("supports fixed resource routes and policy level navigation", async ({ page }) => {
    await page.goto("/asset-center/policy/education-policies?policyLevel=provincial");

    await expect(page.getByRole("heading", { level: 1, name: "教育政策" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "政策层级" })).toBeVisible();
    await expect(page.getByRole("link", { name: "省级政策" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  test("does not expose intermediate domain summary pages", async ({ page }) => {
    await page.goto("/asset-center/policy");

    await expect(page.getByText("页面未找到", { exact: true })).toBeVisible();
    await expect(page.locator("main").getByRole("article")).toHaveCount(0);
  });

  test("redirects retired catalogue and retrieval-test routes", async ({ page }) => {
    await page.goto("/data-assets");
    await expect(page).toHaveURL(/\/asset-center$/);

    await page.goto("/retrieval-test");
    await expect(page).toHaveURL(/\/query$/);
  });
});
