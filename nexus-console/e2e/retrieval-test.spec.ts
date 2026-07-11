import { expect, test } from "@playwright/test";

import { RetrievalTestPage, makeRetrievalResponse, mockRetrievalApi } from "./helpers/page-objects";

test.describe("Retrieval test panel", () => {
  test("renders panel skeleton on first load", async ({ page }) => {
    await mockRetrievalApi(page);
    const retrievalPage = new RetrievalTestPage(page);
    await retrievalPage.goto();

    await expect(retrievalPage.panel).toBeVisible();
    await expect(retrievalPage.queryInput).toBeVisible();
    await expect(retrievalPage.submitButton).toBeVisible();
  });

  test("Plan Only mode renders intent + plan without results", async ({ page }) => {
    await mockRetrievalApi(page, {
      planResponse: makeRetrievalResponse({ hasResults: false }),
    });
    const retrievalPage = new RetrievalTestPage(page);
    await retrievalPage.goto();

    await retrievalPage.submitFreeform("北京的电商运营岗位");

    await expect(retrievalPage.intentSlot).toBeVisible();
    await expect(retrievalPage.planSlot).toBeVisible();
    // Plan Only mode hides the results tabs entirely.
    await expect(retrievalPage.resultsSlot).toHaveCount(0);
    await expect(retrievalPage.warningsSlot).toBeVisible();
  });

  test("Full Run mode renders results tabs and warnings", async ({ page }) => {
    await mockRetrievalApi(page, {
      fullResponse: makeRetrievalResponse({
        hasResults: true,
        warnings: ["weighted_rerank_applied"],
      }),
    });
    const retrievalPage = new RetrievalTestPage(page);
    await retrievalPage.goto();

    await retrievalPage.switchMode("Full Run");
    await retrievalPage.submitFreeform("北京优先电商运营");

    await expect(retrievalPage.intentSlot).toBeVisible();
    await expect(retrievalPage.planSlot).toBeVisible();
    await expect(retrievalPage.resultsSlot).toBeVisible();
    await expect(retrievalPage.warningsSlot).toBeVisible();
    await expect(retrievalPage.warningsSlot).toContainText("weighted_rerank_applied");
  });

  test("shows ApiState banner on backend error", async ({ page }) => {
    await mockRetrievalApi(page, { errorEndpoint: "plans" });
    const retrievalPage = new RetrievalTestPage(page);
    await retrievalPage.goto();

    await retrievalPage.submitFreeform("触发错误的查询");

    await expect(page.getByText("API 不可用")).toBeVisible();
    await expect(page.getByText("e2e mock: plans failure")).toBeVisible();
    // No result slots should render.
    await expect(retrievalPage.intentSlot).toHaveCount(0);
  });
});
