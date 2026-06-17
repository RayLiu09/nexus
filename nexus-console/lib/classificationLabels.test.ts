import { describe, expect, it } from "vitest";
import { buildClassificationDictionary, classificationLabel } from "./classificationLabels";

describe("classificationLabel", () => {
  it("uses governance rules classification names before falling back to code", () => {
    const dictionary = buildClassificationDictionary([
      { code: "sector_report", name: "行业报告" },
      { code: "custom_class", name: "自定义分类" },
    ]);

    expect(classificationLabel("sector_report", dictionary)).toBe("行业报告");
    expect(classificationLabel("custom_class", dictionary)).toBe("自定义分类");
    expect(classificationLabel("unknown", dictionary)).toBe("unknown");
  });
});
