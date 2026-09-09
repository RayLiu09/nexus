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
    await expect(
      page.getByRole("link", { name: /标准课程库，(?:[\d,]+ 条|数量暂不可用)/ }),
    ).toBeVisible();
    await expect(page.getByText("产业画像")).toHaveCount(0);
    await expect(page.getByRole("link", { name: "智能检索", exact: true })).toHaveCount(1);
    await expect(page.getByRole("link", { name: "检索联调" })).toHaveCount(0);

    const domainCards = page.locator("main").getByRole("article");
    const [marketBox, teachingResourceBox, userBehaviorBox] = await Promise.all([
      domainCards.nth(2).boundingBox(),
      domainCards.nth(3).boundingBox(),
      domainCards.nth(4).boundingBox(),
    ]);
    expect(marketBox).not.toBeNull();
    expect(teachingResourceBox).not.toBeNull();
    expect(userBehaviorBox).not.toBeNull();
    const cardBottoms = [marketBox!, teachingResourceBox!, userBehaviorBox!].map(
      (box) => box.y + box.height,
    );
    expect(Math.max(...cardBottoms) - Math.min(...cardBottoms)).toBeLessThanOrEqual(1);

    const teachingResourceLinks = domainCards.nth(3).getByRole("link");
    const teachingResourceLinkBoxes = await Promise.all(
      Array.from({ length: await teachingResourceLinks.count() }, (_, index) =>
        teachingResourceLinks.nth(index).boundingBox(),
      ),
    );
    expect(teachingResourceLinkBoxes).toHaveLength(3);
    for (let index = 1; index < teachingResourceLinkBoxes.length; index += 1) {
      expect(teachingResourceLinkBoxes[index]!.y - teachingResourceLinkBoxes[index - 1]!.y).toBe(
        49,
      );
    }
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

  test("renders professional profiles and lazily expands their domain facts", async ({
    page,
  }, testInfo) => {
    await page.goto("/asset-center/major/profiles");

    await expect(page.getByRole("heading", { level: 1, name: "专业简介" })).toBeVisible();
    for (const heading of ["专业名称", "专业代码", "修业年限", "培养层次", "院校名称"]) {
      await expect(page.getByRole("columnheader", { name: heading })).toBeVisible();
    }
    const rows = page.locator(".ant-table-tbody > tr.ant-table-row");
    expect(await rows.count()).toBeGreaterThan(0);
    await rows.first().locator(".ant-table-row-expand-icon").click();
    const panel = page.getByTestId("major-profile-detail-panel");
    await expect(panel).toBeVisible();
    await expect(panel).toHaveCSS("margin-left", "24px");
    for (const heading of ["职业面向", "培养定位", "能力要求", "课程与实训", "证书信息"]) {
      await expect(panel.getByRole("heading", { level: 4, name: heading })).toBeVisible();
    }
    if (process.env.NEXUS_CAPTURE_SCREENSHOTS) {
      await page.screenshot({
        path: `/tmp/major-profiles-${testInfo.project.name}.png`,
        fullPage: true,
      });
    }
  });

  test("keeps the professional-profile view out of technical asset detail", async ({ page }) => {
    const assetId = process.env.NEXUS_E2E_MAJOR_PROFILE_ASSET_ID;
    test.skip(!assetId, "No professional-profile asset ID was supplied");

    await page.goto(`/assets/${assetId}`);
    await page.getByRole("tab", { name: "知识块" }).click();

    await expect(page.getByLabel("切换专业简介知识视图")).toHaveCount(0);
    await expect(page.getByText("专业图谱", { exact: true })).toHaveCount(0);
    await expect(page.getByText("RAG知识块", { exact: true }).first()).toBeVisible();
  });

  test("renders course textbooks with clean titles and outline drawers", async ({
    page,
  }, testInfo) => {
    const antdWarnings: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "warning" && message.text().includes("[antd:")) {
        antdWarnings.push(message.text());
      }
    });

    await page.goto("/asset-center/teaching-resources/course-textbooks");

    await expect(page.getByRole("heading", { level: 1, name: "课程教材" })).toBeVisible();
    for (const heading of ["教材名称", "类型", "出版社", "主编", "出版年份", "操作"]) {
      await expect(page.getByRole("columnheader", { name: heading })).toBeVisible();
    }
    const rows = page.locator(".ant-table-tbody > tr.ant-table-row");
    await expect(rows).toHaveCount(7);
    const titles = await rows.locator("td:first-child").allTextContents();
    for (const title of titles) {
      expect(title.trim()).not.toMatch(/^\s*(?:\d{1,3}[.．、_：:\-]|[（(]\d{1,3}[）)])/);
      expect(title.trim()).not.toMatch(/\.(?:pdf|docx?|docxp|pptx?|xlsx?|xls|txt|md|html?|rtf|odt)$/i);
    }
    await expect(page.getByText(/Left-to-Right/)).toHaveCount(0);

    await page.getByRole("button", { name: "知识大纲树" }).first().click();
    let dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("知识大纲树");
    await expect(dialog.getByText(/Left-to-Right/)).toHaveCount(0);
    await expect(dialog.locator("[data-outline-layout='orthogonal']")).toBeVisible();
    await expect(dialog.getByText(/\d+ 节点|\d+ 级深度|单节点回退/)).toHaveCount(0);
    await dialog.getByRole("button", { name: /Close|关闭/ }).click();

    await page.getByRole("button", { name: "知识大纲径向图" }).first().click();
    dialog = page.getByRole("dialog");
    await expect(dialog.locator("[data-outline-layout='radial']")).toBeVisible();
    await expect(dialog.getByText(/\d+ 节点|\d+ 级深度|单节点回退/)).toHaveCount(0);
    await dialog.getByRole("button", { name: /Close|关闭/ }).click();

    await page.getByRole("button", { name: "任务大纲树视图" }).first().click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("tree", { name: "任务大纲树" })).toBeVisible();
    await expect(dialog.getByText(/实训操作型|不推荐构图|推荐构图|\d+ chunks/)).toHaveCount(0);
    await dialog.getByRole("button", { name: /Close|关闭/ }).click();

    await page.getByRole("button", { name: "任务大纲圆形树" }).first().click();
    dialog = page.getByRole("dialog");
    await expect(dialog.locator("canvas").first()).toBeVisible({ timeout: 20_000 });
    await expect(dialog.getByText(/实训操作型|不推荐构图|推荐构图|\d+ chunks/)).toHaveCount(0);
    if (process.env.NEXUS_CAPTURE_SCREENSHOTS) {
      await page.screenshot({
        path: `/tmp/course-textbooks-${testInfo.project.name}.png`,
        fullPage: true,
      });
    }
    await dialog.getByRole("button", { name: /Close|关闭/ }).click();

    expect(antdWarnings).toEqual([]);
  });

  test("redirects retired catalogue and retrieval-test routes", async ({ page }) => {
    await page.goto("/data-assets");
    await expect(page).toHaveURL(/\/asset-center$/);

    await page.goto("/retrieval-test");
    await expect(page).toHaveURL(/\/query$/);
  });

  test("renders the professional teaching-standard business list and graph drawer", async ({
    page,
  }, testInfo) => {
    await page.goto("/asset-center/major/teaching-standards");

    await expect(page.getByRole("heading", { level: 1, name: "专业教学标准" })).toBeVisible();
    await expect(page.getByRole("link", { name: "返回专业标准库" })).toHaveCount(0);
    for (const heading of [
      "专业代码",
      "专业名称",
      "专业大类",
      "专业类",
      "培养层次",
      "修业年限",
      "操作",
    ]) {
      await expect(page.getByRole("columnheader", { name: heading })).toBeVisible();
    }
    await expect(page.getByRole("button", { name: /课程库/ }).first()).toBeVisible();
    await page
      .getByRole("button", { name: /职业领域图谱/ })
      .first()
      .click();
    await expect(page.getByRole("dialog")).toContainText("职业领域图谱");
    await expect(page.getByText(/专业 → 职业领域 → 典型工作任务/)).toHaveCount(0);
    await expect(page.getByText("generated", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("checkbox", { name: /显示边/ })).toHaveCount(0);
    const graphCanvas = page.getByRole("dialog").locator("canvas").first();
    await expect(graphCanvas).toBeVisible({ timeout: 20_000 });
    await expect
      .poll(
        () =>
          graphCanvas.evaluate((canvas: HTMLCanvasElement) => {
            const context = canvas.getContext("2d");
            if (!context || canvas.width === 0 || canvas.height === 0) return 0;
            const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
            let colored = 0;
            for (let index = 0; index < pixels.length; index += 16) {
              if (
                pixels[index + 3] > 0 &&
                (pixels[index] < 245 || pixels[index + 1] < 245 || pixels[index + 2] < 245)
              ) {
                colored += 1;
              }
            }
            return colored;
          }),
        { timeout: 20_000 },
      )
      .toBeGreaterThan(100);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    if (process.env.NEXUS_CAPTURE_SCREENSHOTS) {
      await page.screenshot({
        path: `/tmp/teaching-standards-graph-${testInfo.project.name}.png`,
        fullPage: true,
      });
    }
  });

  test("renders the cross-dataset professional distribution business list", async ({ page }) => {
    const antdWarnings: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "warning" && message.text().includes("[antd:")) {
        antdWarnings.push(message.text());
      }
    });
    await page.goto("/asset-center/major/distributions");

    await expect(page.getByRole("heading", { level: 1, name: "专业布点数据" })).toBeVisible();
    await expect(page.getByText("暂无可用业务视图")).toHaveCount(0);
    for (const heading of [
      "年份",
      "省份",
      "专业名称",
      "专业代码",
      "培养层次",
      "区域",
      "布点数",
      "操作",
    ]) {
      await expect(page.getByRole("columnheader", { name: heading })).toBeVisible();
    }
    await expect(page.getByRole("button", { name: /编辑/ }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: /删除/ }).first()).toBeVisible();
    expect(antdWarnings).toEqual([]);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  });

  test("keeps the professional distribution list out of technical asset detail", async ({
    page,
  }) => {
    const assetId = process.env.NEXUS_E2E_MAJOR_DISTRIBUTION_ASSET_ID;
    test.skip(!assetId, "No professional-distribution asset ID was supplied");

    await page.goto(`/assets/${assetId}`);

    await expect(page.getByRole("tab", { name: "结构化图谱" })).toHaveCount(0);
    await expect(page.getByText("专业布点列表")).toHaveCount(0);
  });

  test("renders occupational analyses and the three migrated views", async ({ page }) => {
    const antdWarnings: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "warning" && message.text().includes("[antd:")) {
        antdWarnings.push(message.text());
      }
    });
    await page.goto("/asset-center/major/occupation-analyses");

    await expect(page.getByRole("heading", { level: 1, name: "职业能力分析" })).toBeVisible();
    for (const heading of [
      "专业名称",
      "分析模型",
      "典型任务数",
      "通用能力数",
      "发展能力数",
      "职业能力数",
      "社会能力数",
      "操作",
    ]) {
      await expect(page.getByRole("columnheader", { name: heading })).toBeVisible();
    }
    const firstAnalysisRow = page.locator(".ant-table-tbody > tr.ant-table-row").first();
    for (const columnIndex of [2, 3, 4, 5, 6]) {
      await expect(firstAnalysisRow.locator("td").nth(columnIndex)).toHaveText(/^\d+$/);
    }

    await page
      .getByRole("button", { name: /能力条目/ })
      .first()
      .click();
    let dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("能力条目");
    await expect(dialog.getByRole("columnheader")).toHaveCount(3);
    for (const heading of ["类别", "能力描述", "对应任务名称"]) {
      await expect(dialog.getByRole("columnheader", { name: heading })).toBeVisible();
    }
    await dialog.getByRole("button", { name: "关闭" }).click();

    await page
      .getByRole("button", { name: /能力树/ })
      .first()
      .click();
    dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("能力树");
    await expect(dialog.getByRole("tree", { name: "能力分析任务树" })).toBeVisible();
    await dialog.getByRole("button", { name: "关闭" }).click();

    await page
      .getByRole("button", { name: /能力图谱/ })
      .first()
      .click();
    dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("能力图谱");
    const graphCanvas = dialog.locator("canvas").first();
    await expect(graphCanvas).toBeVisible({ timeout: 20_000 });
    await expect
      .poll(
        () =>
          graphCanvas.evaluate((canvas: HTMLCanvasElement) => {
            const context = canvas.getContext("2d");
            if (!context || canvas.width === 0 || canvas.height === 0) return 0;
            const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
            let colored = 0;
            for (let index = 0; index < pixels.length; index += 16) {
              if (
                pixels[index + 3] > 0 &&
                (pixels[index] < 245 || pixels[index + 1] < 245 || pixels[index + 2] < 245)
              ) {
                colored += 1;
              }
            }
            return colored;
          }),
        { timeout: 20_000 },
      )
      .toBeGreaterThan(100);
    expect(antdWarnings).toEqual([]);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  });

  test("renders talent training plans and the two migrated graph drawers", async ({
    page,
  }, testInfo) => {
    const antdWarnings: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "warning" && message.text().includes("[antd:")) {
        antdWarnings.push(message.text());
      }
    });
    await page.goto("/asset-center/major/training-plans");

    await expect(page.getByRole("heading", { level: 1, name: "人才培养方案" })).toBeVisible();
    for (const heading of ["专业名称", "专业代码", "修业年限", "培养层次", "院校名称", "操作"]) {
      await expect(page.getByRole("columnheader", { name: heading })).toBeVisible();
    }

    await page.locator(".ant-table-row-expand-icon").first().click();
    await expect(page.getByRole("heading", { level: 4, name: "专业归属" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 4, name: "职业面向" })).toBeVisible();
    await expect(page.getByTestId("career-orientation-panel")).toHaveCSS(
      "margin-left",
      "24px",
    );
    for (const label of [
      "专业大类（代码）",
      "专业类（代码）",
      "所属行业",
      "职业类别",
      "岗位名称",
    ]) {
      await expect(page.getByText(label, { exact: true })).toBeVisible();
    }
    if (process.env.NEXUS_CAPTURE_SCREENSHOTS) {
      await page.screenshot({
        path: `/tmp/talent-training-plans-${testInfo.project.name}.png`,
        fullPage: true,
      });
    }

    await page
      .getByRole("button", { name: /课程知识图谱/ })
      .first()
      .click();
    let dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("课程知识图谱");
    await dialog.getByRole("button", { name: "关闭" }).click();

    await page
      .getByRole("button", { name: /岗位能力图谱/ })
      .first()
      .click();
    dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("岗位能力图谱");
    expect(antdWarnings).toEqual([]);
  });

  test("keeps talent training plan graphs out of technical asset detail", async ({ page }) => {
    const assetId = process.env.NEXUS_E2E_TALENT_TRAINING_PLAN_ASSET_ID;
    test.skip(!assetId, "No talent-training-plan asset ID was supplied");

    await page.goto(`/assets/${assetId}`);
    await page.getByRole("tab", { name: "知识块" }).click();

    await expect(page.getByText("课程知识图谱", { exact: true })).toHaveCount(0);
    await expect(page.getByText("岗位能力图谱", { exact: true })).toHaveCount(0);
    await expect(page.getByText("RAG知识块", { exact: true }).first()).toBeVisible();
  });

  test("keeps occupational ability views out of technical asset detail", async ({ page }) => {
    const assetId = process.env.NEXUS_E2E_ABILITY_ANALYSIS_ASSET_ID;
    test.skip(!assetId, "No occupational-ability asset ID was supplied");

    await page.goto(`/assets/${assetId}`);

    await expect(page.getByRole("tab", { name: "结构化图谱" })).toHaveCount(0);
    await expect(page.getByText("能力条目", { exact: true })).toHaveCount(0);
  });

  test("renders the expandable standard-course library and evidence drawer", async ({
    page,
  }, testInfo) => {
    const antdWarnings: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "warning" && message.text().includes("[antd:")) {
        antdWarnings.push(message.text());
      }
    });
    await page.goto("/asset-center/major/standard-course-library");

    await expect(page.getByRole("heading", { level: 1, name: "标准课程库" })).toBeVisible();
    const backLink = page.getByRole("link", { name: "返回专业标准库" });
    await expect(backLink).toHaveAttribute("href", "/asset-center/major/teaching-standards");
    await backLink.click();
    await expect(page).toHaveURL(/\/asset-center\/major\/teaching-standards$/);
    await expect(page.getByRole("heading", { level: 1, name: "专业教学标准" })).toBeVisible();
    await page.goto("/asset-center/major/standard-course-library");
    for (const heading of [
      "课程唯一编号",
      "课程名称",
      "专业代码",
      "专业名称",
      "培养层次",
      "课程类型",
      "建议总学时",
      "建议实践学时",
      "建议学时区间",
      "操作",
    ]) {
      await expect(page.getByRole("columnheader", { name: heading })).toBeVisible();
    }
    await expect(page.getByRole("spinbutton", { name: /建议总学时/ }).first()).toBeVisible();
    await page.locator(".ant-table-row-expand-icon").first().click();
    await expect(page.getByText("典型工作任务", { exact: true })).toBeVisible();
    await expect(page.getByText("主要教学内容与要求", { exact: true })).toBeVisible();
    await expect(page.getByText("知识标签", { exact: true })).toBeVisible();
    await page
      .getByRole("button", { name: /血缘追溯/ })
      .first()
      .click();
    await expect(page.getByRole("dialog")).toContainText("学时设置依据");
    await expect(page.getByRole("dialog")).toContainText("证据绑定");
    expect(antdWarnings).toEqual([]);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    if (process.env.NEXUS_CAPTURE_SCREENSHOTS) {
      await page.screenshot({
        path: `/tmp/standard-course-evidence-${testInfo.project.name}.png`,
        fullPage: true,
      });
    }
  });
});
