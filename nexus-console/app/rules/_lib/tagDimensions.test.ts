import { expect, it } from "vitest";
import rules from "../../../../config/governance_rules_v2.json";
import { extractTagDimensions } from "./tagDimensions";

it("loads current tag dimensions and their per-classification evidence", () => {
  const rows = extractTagDimensions(rules as Record<string, unknown>);

  expect(rows.map((row) => row.name)).toEqual([
    "专业领域", "学历层次", "地域范围", "时效性", "数据来源",
  ]);
  expect(rows.find((row) => row.code === "education_level")?.values).toContain("高职");
  expect(rows.find((row) => row.code === "professional_domain")?.details)
    .toContainEqual(expect.objectContaining({
      code: "industry_policy",
      criteria: expect.arrayContaining([expect.stringContaining("数字经济")]),
    }));
  expect(rows.find((row) => row.code === "geographic_scope")?.details)
    .toContainEqual(expect.objectContaining({ code: "industry_policy" }));
  expect(rows.find((row) => row.code === "timeliness")?.details.length).toBeGreaterThan(0);
  expect(rows.find((row) => row.code === "data_source_type")?.details.length).toBeGreaterThan(0);
});
