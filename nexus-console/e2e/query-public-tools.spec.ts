import { expect, test } from "@playwright/test";

const citation = {
  citation_id: "1",
  source_type: "aggregate",
  title: "重庆电子商务专业布点统计",
  excerpt: "已入库数据：院校数 3，布点记录数 4。",
  tool: "aggregate_major_offerings",
  scope: { province: "重庆" },
};

function frame(event: string, data: object) {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

test.beforeEach(async ({ context, page }) => {
  const payload = Buffer.from(
    JSON.stringify({ role: "business_expert", exp: 4102444800 }),
  ).toString("base64url");
  await context.addCookies([
    { name: "nexus_access_token", value: `e2e.${payload}.signature`, url: "http://127.0.0.1:3000" },
  ]);
  await page.route("**/api/auth/session", (route) =>
    route.fulfill({
      json: {
        data: {
          id: "e2e-user",
          username: "e2e",
          displayName: "验收用户",
          role: "business_expert",
          orgUnit: { id: "", name: "" },
        },
      },
    }),
  );
});

test("chat submits, shows execution facts and opens citation source", async ({
  page,
}, testInfo) => {
  if (testInfo.project.name === "chromium-tablet")
    await page.setViewportSize({ width: 390, height: 844 });
  else await page.setViewportSize({ width: 1920, height: 1080 });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/query/stream", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body:
        frame("meta", { intent: "public_tools", turn_id: "turn-e2e" }) +
        frame("step", {
          id: "tool-1",
          label: "统计专业布点",
          status: "completed",
          input: {},
          output: {
            outcome: "success",
            source_count: 1,
            new_source_count: 1,
            total_source_count: 1,
          },
          started_at_ms: 1000,
          completed_at_ms: 1100,
        }) +
        frame("meta", { citations: [citation] }) +
        frame("chunk", { text: "重庆已入库院校数为 **3** [1]。" }) +
        frame("final", {
          markdown: "重庆已入库院校数为 **3** [1]。",
          intent: "public_tools",
          intent_confidence: 0,
          invoked_tools: ["aggregate_major_offerings"],
          warnings: [],
          citations: [citation],
          audit_summary: {},
          external_web_results: [],
          fallback_reason: null,
        }) +
        frame("done", { ok: true }),
    }),
  );
  await page.goto("/query");
  await expect(page.getByText("从问题开始，找到有据可查的答案")).toBeVisible();
  await page.getByRole("textbox").fill("重庆电子商务专业布点数量");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  const sources = page.getByLabel("引用来源", { exact: true });
  await expect(sources).toBeVisible();
  await expect(sources).not.toHaveAttribute("open");
  await expect(sources.getByRole("button")).not.toBeVisible();
  const composer = await page.getByTestId("query-composer").boundingBox();
  const turn = await page.getByTestId("query-turn").boundingBox();
  expect(Math.abs(composer!.width - turn!.width)).toBeLessThan(4);
  if (testInfo.project.name === "chromium-desktop") expect(composer!.width).toBeGreaterThan(1400);
  await page.getByRole("link", { name: "1", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByText("引用 [1] · 重庆电子商务专业布点统计")).toBeVisible();
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await page.locator("summary").filter({ hasText: "查看执行过程" }).click();
  await expect(page.getByText("统计专业布点", { exact: true })).toBeVisible();
  await expect(page.getByText("本次取得 1 条候选资料", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: `/tmp/nexus-chat-${testInfo.project.name}.png`, fullPage: true });
});

test("Enter submits, Shift+Enter inserts a newline, and IME Enter does not submit", async ({
  page,
}) => {
  const queries: string[] = [];
  await page.route("**/api/query/stream", async (route) => {
    queries.push(route.request().postDataJSON().query);
    await route.fulfill({ contentType: "text/event-stream", body: frame("done", { ok: false }) });
  });
  await page.goto("/query");
  const input = page.getByRole("textbox");
  await input.fill("第一行");
  await input.press("End");
  await input.press("Shift+Enter");
  await input.pressSequentially("second line");
  await expect(input).toHaveValue("第一行\nsecond line");
  expect(queries).toHaveLength(0);
  await input.dispatchEvent("compositionstart");
  await input.dispatchEvent("keydown", { key: "Enter", code: "Enter", isComposing: true });
  expect(queries).toHaveLength(0);
  await input.dispatchEvent("compositionend");
  await input.press("Enter");
  await expect.poll(() => queries).toEqual(["第一行\nsecond line"]);
  await expect(input).toHaveValue("");
});

test("stop ends the turn and allows another query", async ({ page }) => {
  await page.route("**/api/query/stream", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    try {
      await route.fulfill({ contentType: "text/event-stream", body: frame("done", { ok: false }) });
    } catch {
      /* request was cancelled */
    }
  });
  await page.goto("/query");
  await page.getByRole("textbox").fill("查询市场岗位");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await page.getByRole("button", { name: "停止生成" }).click();
  await expect(page.getByText("本次查询已停止。")).toBeVisible();
  await expect(page.getByRole("textbox")).toBeEditable();
  await page.getByRole("textbox").fill("新的查询");
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeEnabled();
});

test("web switch is explicit and a cited document opens actual content preview", async ({ page }, testInfo) => {
  if (testInfo.project.name === "chromium-tablet") await page.setViewportSize({ width: 390, height: 844 });
  const documentCitation = { ...citation, source_type: "document", title: "重庆低空经济政策", normalized_ref_id: "preview-ref", evidence_level: "metadata" };
  const requests: { web_search: boolean }[] = [];
  let contentReads = 0;
  await page.route("**/api/normalized-refs/preview-ref/content", (route) => {
    contentReads += 1;
    return route.fulfill({ json: { ok: true, data: { body_markdown: "# 低空经济政策正文\n\n在重庆建设低空产业集群，发展飞行器制造与运营服务。" } } });
  });
  await page.route("**/api/query/stream", (route) => {
    requests.push(route.request().postDataJSON());
    return route.fulfill({ contentType: "text/event-stream", body:
      frame("meta", { intent: "public_tools", citations: [documentCitation, { ...documentCitation, citation_id: "2", title: "未引用候选资料" }] }) +
      frame("chunk", { text: "已检索到政策元数据 [1]。" }) +
      frame("final", { markdown: "已检索到政策元数据 [1]。", citations: [documentCitation], warnings: [], audit_summary: {} }) +
      frame("done", { ok: true }),
    });
  });
  await page.goto("/query");
  const toggle = page.getByRole("switch", { name: "联网搜索" });
  await expect(toggle).not.toBeChecked();
  await expect(page.getByText("资料不足时补充联网搜索，并为回答标注来源。")).toHaveCount(0);
  await page.getByRole("textbox").fill("查找重庆低空政策");
  await page.getByRole("textbox").press("Enter");
  await expect(page.getByText("引用来源 · 1")).toBeVisible();
  expect(requests[0].web_search).toBe(false);
  expect(contentReads).toBe(0);
  await page.getByRole("link", { name: "1", exact: true }).click();
  await expect(page.getByRole("heading", { name: "低空经济政策正文" })).toBeVisible();
  await expect(page.getByText(/发展飞行器制造与运营服务/)).toBeVisible();
  await expect(page.getByRole("link", { name: "查看平台资产" })).toHaveCount(0);
  // Next dev StrictMode can mount the preview effect twice; both reads are lazy.
  expect(contentReads).toBeGreaterThan(0);
  expect(contentReads).toBeLessThanOrEqual(2);
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await toggle.click();
  await expect(toggle).toBeChecked();
  await page.getByRole("textbox").fill("查找低空产业链");
  await page.getByRole("textbox").press("Enter");
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1].web_search).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `/tmp/nexus-query-web-${testInfo.project.name}.png`, fullPage: true });
});

test("long citation cards clamp to six lines while previews and web resource links remain available", async ({ page }, testInfo) => {
  await page.setViewportSize(testInfo.project.name === "chromium-tablet"
    ? { width: 390, height: 844 } : { width: 1920, height: 1080 });
  const longExcerpt = "重庆低空经济政策支持飞行器制造、运营服务与产业园区建设。".repeat(150);
  const sources = [
    { ...citation, source_type: "external_web", title: "重庆低空经济公开资料", excerpt: longExcerpt,
      asset_id: "asset-anchor", url: "https://example.com/policy" },
    { ...citation, citation_id: "2", title: "简短统计资料" },
  ];
  await page.route("**/api/query/stream", (route) => route.fulfill({
    contentType: "text/event-stream", body:
      frame("meta", { intent: "public_tools", citations: sources }) +
      frame("final", { markdown: "政策与统计 [1] [2]。", citations: sources, warnings: [], audit_summary: {} }) +
      frame("done", { ok: true }),
  }));
  await page.goto("/query");
  await expect(page.getByText("本页保留记录 · 每次查询独立执行")).toHaveCount(0);
  await page.getByRole("switch", { name: "联网搜索" }).click();
  await page.getByRole("textbox").fill("检索重庆低空经济政策");
  await page.getByRole("textbox").press("Enter");
  await page.getByText("引用来源 · 2").click();
  const cards = page.getByLabel("引用来源", { exact: true }).getByRole("button");
  const excerpt = cards.first().locator("span").last();
  await expect(excerpt).toBeVisible();
  const geometry = await excerpt.evaluate((element) => {
    const style = getComputedStyle(element);
    return { clamp: style.webkitLineClamp, lineHeight: parseFloat(style.lineHeight),
      height: element.getBoundingClientRect().height, fullHeight: element.scrollHeight };
  });
  expect(geometry.clamp).toBe("6");
  expect(geometry.height).toBeLessThanOrEqual(geometry.lineHeight * 6 + 1);
  expect(geometry.fullHeight).toBeGreaterThan(geometry.height);
  const longCard = await cards.first().boundingBox();
  const shortCard = await cards.nth(1).boundingBox();
  expect(longCard!.height).toBeLessThan(200);
  expect(shortCard!.height).toBeLessThan(longCard!.height - 20);
  await page.screenshot({ path: `/tmp/nexus-query-cards-${testInfo.project.name}.png`, fullPage: true });
  await cards.first().click();
  const drawer = page.getByRole("dialog");
  const link = drawer.getByRole("link", { name: "打开网络资源" });
  await expect(link).toHaveAttribute("href", "https://example.com/policy");
  await expect(link).toHaveAttribute("target", "_blank");
  await expect(link).toHaveAttribute("rel", "noopener noreferrer");
  await expect(drawer.getByRole("link", { name: "查看平台资产" })).toHaveCount(0);
  await expect(drawer.getByText(longExcerpt, { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
