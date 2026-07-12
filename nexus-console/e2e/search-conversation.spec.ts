import { expect, test, type Page } from "@playwright/test";

import { makeRetrievalResponse } from "./helpers/page-objects";

/**
 * Cover the M-C v1.3 refinement UX loop that landed in PR 2:
 *   1. Assistant returns `needs_clarification` with a suggested_refinement list.
 *   2. User clicks one of the refinement buttons.
 *   3. `applyRefinement` auto-submits the refinement as a new retrieval query.
 *   4. Second response (completed) renders in the conversation feed.
 *
 * We intercept /api/knowledge-retrieval on the console proxy layer so the
 * spec never touches nexus-api and doesn't depend on a live LiteLLM.
 */

async function goSearchPageAuthed(page: Page) {
  await page.context().addCookies([
    {
      name: "nexus_access_token",
      value: "e2e-fake-token",
      domain: "localhost",
      path: "/",
    },
  ]);
  await page.goto("/search");
}

test.describe("Search page — M-C v1.3 clarification refinement", () => {
  test("clicking a refinement auto-runs a new retrieval query", async ({ page }) => {
    const responses = [
      // First call: needs_clarification with two refinement buttons.
      {
        ...(makeRetrievalResponse() as Record<string, unknown>),
        status: "needs_clarification",
        markdown: null,
        clarification: {
          message: "请补充需要缩小到哪个地区。",
          suggested_refinements: ["北京", "上海"],
          missing_constraints: ["regions"],
          candidate_intents: [],
        },
      },
      // Second call: completed, comes back after the user clicks "北京".
      {
        ...(makeRetrievalResponse() as Record<string, unknown>),
        status: "completed",
        original_query: "北京",
      },
    ];

    let callIdx = 0;
    await page.route("**/api/knowledge-retrieval", async (route) => {
      const data = responses[Math.min(callIdx, responses.length - 1)];
      callIdx += 1;
      await route.fulfill({
        json: {
          ok: true,
          status: 200,
          data,
          traceId: `e2e-conv-${callIdx}`,
        },
      });
    });

    await goSearchPageAuthed(page);

    // Composer sits at the bottom; the shared placeholder is the safest
    // handle without adding new testids to production code.
    const textarea = page.getByPlaceholder("输入需要检索/召回的问题");
    await textarea.fill("电商岗位");
    await textarea.press("Enter");

    await expect(page.getByTestId("clarification-panel")).toBeVisible();
    const refinements = page.getByTestId("clarification-refinements");
    await expect(refinements).toBeVisible();
    // Antd 6 auto-inserts a space between two CJK chars in <Button>
    // labels (rendered as `<span>北 京</span>`) — match either form so
    // the spec stays robust to that display-only quirk. The click still
    // fires applyRefinement("北京") since the callback binds the raw
    // string, not the displayed text.
    const bjButton = refinements.locator("button", { hasText: /北\s*京/ });
    await expect(bjButton).toBeVisible({ timeout: 10_000 });
    await bjButton.click();

    // A new completed assistant reply lands with the MarkdownAnswer header,
    // and the proxy should have received two POSTs by now.
    await expect(page.getByText("结构化结果")).toBeVisible({ timeout: 10_000 });
    expect(callIdx).toBeGreaterThanOrEqual(2);
  });
});
