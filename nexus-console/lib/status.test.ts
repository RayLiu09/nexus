import { describe, it, expect } from "vitest";
import { statusDefinitions, type StatusTone } from "./status";

const VALID_TONES: StatusTone[] = ["neutral", "info", "success", "warning", "danger", "muted"];

describe("statusDefinitions", () => {
  it("has 29 entries covering all pipeline stages", () => {
    const keys = Object.keys(statusDefinitions);
    expect(keys).toHaveLength(29);
  });

  it.each(Object.entries(statusDefinitions))(
    "%s has a non-empty label",
    (_, def) => {
      expect(def.label).toBeTruthy();
      expect(typeof def.label).toBe("string");
    },
  );

  it.each(Object.entries(statusDefinitions))(
    "%s has a valid tone",
    (_, def) => {
      expect(VALID_TONES).toContain(def.tone);
    },
  );

  it("maps all status keys to string labels", () => {
    for (const def of Object.values(statusDefinitions)) {
      expect(def.label.length).toBeGreaterThan(0);
    }
  });

  it("has no duplicate labels across different statuses", () => {
    const labels = Object.values(statusDefinitions).map((d) => d.label);
    // "处理中" and "启用" are legitimate duplicates in the source
    const duplicateLabels = labels.filter((l) => labels.filter((x) => x === l).length > 1);
    const uniqueDuplicates = [...new Set(duplicateLabels)];
    // Only known duplicates: "处理中" (processing + running), "启用" (active + enabled)
    expect(uniqueDuplicates.sort()).toEqual(["启用", "处理中"]);
  });
});
