import { expect, test } from "@playwright/test";

import {
  RetrievalTestPage,
  makeFriendlyView,
  makeRetrievalResponse,
  mockRetrievalApi,
} from "./helpers/page-objects";

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
    // FriendlyView slot always renders — empty placeholder when the
    // backend did not attach a friendly_view (this fixture's case).
    await expect(retrievalPage.friendlyPlanSlot).toBeVisible();
    await expect(
      retrievalPage.friendlyPlanSlot.getByTestId("friendly-plan-view-empty"),
    ).toBeVisible();
    // Plan Only mode hides the results tabs entirely.
    await expect(retrievalPage.resultsSlot).toHaveCount(0);
    await expect(retrievalPage.warningsSlot).toBeVisible();
  });

  test("renders FriendlyPlanView when backend attaches friendly_view", async ({ page }) => {
    await mockRetrievalApi(page, {
      fullResponse: makeRetrievalResponse({
        hasResults: true,
        friendlyView: makeFriendlyView(),
      }),
    });
    const retrievalPage = new RetrievalTestPage(page);
    await retrievalPage.goto();

    await retrievalPage.switchMode("Full Run");
    await retrievalPage.submitFreeform("北京的电商运营岗位");

    const friendly = retrievalPage.friendlyPlanSlot.getByTestId("friendly-plan-view");
    await expect(friendly).toBeVisible();
    // Intent summary renders the natural-language description.
    await expect(friendly.getByTestId("friendly-intent-summary")).toContainText(
      "查询北京地区的电商运营岗位需求",
    );
    // Exactly one sub_query card, with hit-count summary from result_summary.
    await expect(friendly.getByTestId("friendly-sub-query-card")).toHaveCount(1);
    await expect(friendly.getByTestId("friendly-sub-query-result")).toContainText("156 条记录");
    // Overall footer surfaces the combine strategy.
    await expect(friendly.getByTestId("friendly-overall-summary")).toContainText(
      "所有维度均需匹配（AND）",
    );
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

  test("clicking a source_ref opens the chunk preview drawer", async ({ page }) => {
    const responseWithSourceRef = {
      ...(makeRetrievalResponse({ hasResults: true }) as Record<string, unknown>),
      source_refs: [
        {
          source_ref_id: "sr-e2e-1",
          channel: "structured",
          domain: "job_demand",
          asset_id: "asset-1",
          asset_version_id: "ver-1",
          normalized_ref_id: "nref-1",
          chunk_id: "chunk-e2e-1",
          record_ref: null,
          locator: {},
          score: 0.42,
          metadata: {},
        },
      ],
    };
    await mockRetrievalApi(page, { fullResponse: responseWithSourceRef });

    // ChunkPreviewDrawer fetches this endpoint by chunk_id. Return a
    // minimal ChunkPreviewResponse — just enough for the drawer header.
    await page.route("**/api/knowledge-chunks/chunk-e2e-1/preview", async (route) => {
      await route.fulfill({
        json: {
          ok: true,
          status: 200,
          data: {
            chunk: {
              chunk_id: "chunk-e2e-1",
              id: "chunk-e2e-1",
              nexus_chunk_id: "chunk-e2e-1",
              content: "这是引用原文的正文。",
              knowledge_type_code: "textbook_kb",
            },
            normalized_ref: {
              ref_id: "nref-1",
              asset_id: "asset-1",
              version_id: "ver-1",
              normalized_type: "document",
            },
            source: { body_markdown: null, blocks: null, record_body: null },
            highlight: {
              markdown_ranges: [],
              page_anchors: [],
              heading_path: [],
            },
          },
          traceId: "e2e-preview-001",
        },
      });
    });

    const retrievalPage = new RetrievalTestPage(page);
    await retrievalPage.goto();
    await retrievalPage.switchMode("Full Run");
    await retrievalPage.submitFreeform("北京优先电商运营");

    await expect(retrievalPage.resultsSlot).toBeVisible();
    // Switch to the source_refs tab so the ref row appears.
    await retrievalPage.resultsSlot.getByRole("tab", { name: /source_refs/ }).click();
    const refRow = retrievalPage.resultsSlot.locator(
      '[data-testid="source-ref-row"][data-clickable="true"]',
    );
    await expect(refRow).toBeVisible();
    await refRow.click();

    // Drawer surfaces the chunk preview content.
    await expect(page.getByText("这是引用原文的正文。")).toBeVisible();
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
