import { expect, it } from "vitest";
import { classificationCriteria } from "./_lib/classificationCriteria";

it("shows classification judgment from the configured definition and keywords", () => {
  const criteria = classificationCriteria({
      code: "industry_policy",
      name: "产业政策",
      description: "政府发布的产业政策",
      title_keywords: ["发展规划", "行动计划"],
      content_keywords: ["重点任务", "保障措施"],
  });

  expect(criteria).toEqual([
    "定义：政府发布的产业政策",
    "标题/封面关键词：发展规划、行动计划",
    "正文/结构关键词：重点任务、保障措施",
  ]);
});
