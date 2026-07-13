import { expect, test, type Page } from "@playwright/test";

import { makeFriendlyView, makeRetrievalResponse } from "./helpers/page-objects";

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

test.describe("Search page — M-C v1.3 four-layer embed", () => {
  test("assistant bubble renders friendly_view + intent/plan/results/warnings collapse", async ({
    page,
  }) => {
    // Backend contract post-#11: retrieval_plan.friendly_view is ALWAYS
    // attached.  This spec pins the assistant bubble against the shape
    // production emits — a regression that drops any of the four layers
    // (friendly_view / intent / plan / results / warnings) fails here.
    const response = {
      ...(makeRetrievalResponse({
        warnings: ["weighted_rerank_applied", "optional_bucket_empty"],
      }) as Record<string, unknown>),
    };
    // Replace retrieval_plan with a version that carries a populated
    // friendly_view — the base helper leaves it null.
    (response as { retrieval_plan: Record<string, unknown> }).retrieval_plan = {
      original_query: "北京的电商运营岗位",
      sub_queries: [
        {
          query_id: "q1",
          channel: "structured",
          domain: "job_demand",
          purpose: "regions_narrow",
          query_text: "北京岗位",
          structured_plan: {
            table_profile: "job_demand.v1",
            query_profile: "job_demand.record_list",
          },
          unstructured_plan: null,
        },
      ],
      merge_goal: "regions tag_filter 收窄",
      friendly_view: makeFriendlyView(),
    };

    await page.route("**/api/knowledge-retrieval", async (route) => {
      await route.fulfill({
        json: { ok: true, status: 200, data: response, traceId: "e2e-4layer-1" },
      });
    });

    await goSearchPageAuthed(page);
    const textarea = page.getByPlaceholder("输入需要检索/召回的问题");
    await textarea.fill("北京电商岗位");
    await textarea.press("Enter");

    // Layer 1 — friendly_view (v1.3 §5.5 natural-language projection)
    // renders ABOVE the Collapse so users see reasoning first.
    await expect(page.getByTestId("friendly-plan-view")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText("查询北京地区的电商运营岗位需求")).toBeVisible();

    // Layer 2 — Collapse header for "意图识别" is the entry point to
    // IntentCard.  It expands by default (defaultActiveKey includes intent).
    await expect(page.getByText("意图识别")).toBeVisible();

    // Layer 3 — "检索计划" header is present (Collapse item may be
    // collapsed; existence proves the panel wired PlanSection in).
    await expect(page.getByText("检索计划")).toBeVisible();

    // Layer 4 — "执行结果" carries the result count in the label.
    await expect(page.getByText(/执行结果.*\(1\)/)).toBeVisible();

    // Layer 5 — warnings header shows the count from the response.
    // Two warnings were requested; catalog translates them client-side.
    await expect(page.getByText(/告警.*\(2\)/)).toBeVisible();
  });

  test("warnings collapse uses the shared catalog labels", async ({ page }) => {
    // Consumers of the same catalog (retrieval-test + search) must render
    // the same Chinese labels for the same codes.  If the shared module
    // ever drifts, this spec catches it in search's context.
    const response = {
      ...(makeRetrievalResponse({
        warnings: ["weighted_rerank_applied"],
      }) as Record<string, unknown>),
    };
    (response as { retrieval_plan: Record<string, unknown> }).retrieval_plan = {
      original_query: "q",
      sub_queries: [
        {
          query_id: "q1",
          channel: "structured",
          domain: "job_demand",
          purpose: "regions_narrow",
          query_text: "x",
          structured_plan: {
            table_profile: "job_demand.v1",
            query_profile: "job_demand.record_list",
          },
          unstructured_plan: null,
        },
      ],
      merge_goal: "",
      friendly_view: makeFriendlyView(),
    };

    await page.route("**/api/knowledge-retrieval", async (route) => {
      await route.fulfill({
        json: { ok: true, status: 200, data: response, traceId: "e2e-warn" },
      });
    });

    await goSearchPageAuthed(page);
    const textarea = page.getByPlaceholder("输入需要检索/召回的问题");
    await textarea.fill("测试告警");
    await textarea.press("Enter");

    await expect(page.getByText(/告警.*\(1\)/)).toBeVisible({ timeout: 10_000 });
    // Expand the warnings section so the catalog label becomes assertable.
    await page.getByText(/告警.*\(1\)/).click();
    await expect(page.getByText("WEIGHTED 已重排")).toBeVisible();
  });
});
